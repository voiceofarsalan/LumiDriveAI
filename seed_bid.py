#!/usr/bin/env python
import os
import sys
import decimal
import psycopg2
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()


def main():
    if len(sys.argv) < 2:
        print("Usage: python seed_bid.py <ride_request_id> [price] [rider_id]")
        print("Example: python seed_bid.py 65b0ed2b-e155-4ba0-a268-73d4c0610ed7 750")
        print("         python seed_bid.py 65b0ed2b-e155-4ba0-a268-73d4c0610ed7 750 <rider_uuid>")
        sys.exit(1)

    ride_request_id = sys.argv[1].strip()

    # Optional price argument, default 750.00
    if len(sys.argv) >= 3:
        price = decimal.Decimal(sys.argv[2])
    else:
        price = decimal.Decimal("750.00")

    # Optional rider_id from CLI
    cli_rider_id = sys.argv[3].strip() if len(sys.argv) >= 4 else None

    db_type = os.getenv("DB_TYPE", "postgres")
    if db_type.lower() != "postgres":
        print(f"Unsupported DB_TYPE: {db_type} (expected 'postgres')")
        sys.exit(1)

    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT", "5432")
    db_user = os.getenv("DB_USERNAME")
    db_pass = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME")

    if not all([db_host, db_user, db_pass, db_name]):
        print("Missing one or more DB_* environment variables:")
        print("  DB_HOST, DB_PORT, DB_USERNAME, DB_PASSWORD, DB_NAME")
        sys.exit(1)

    # Neon-specific: endpoint ID is first part of host, e.g. "ep-xxx" from "ep-xxx.region.neon.tech"
    endpoint_id = db_host.split(".")[0]

    conn = None
    try:
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_pass,
            dbname=db_name,
            sslmode="require",                 # Neon requires SSL
            options=f"endpoint={endpoint_id}", # Neon endpoint ID
        )
        conn.autocommit = True
        cur = conn.cursor()

        # ------------------------------
        # 1) Resolve rider_id
        # ------------------------------
        rider_id = None

        if cli_rider_id:
            rider_id = cli_rider_id
            print(f"🔑 Using rider_id from CLI: {rider_id}")
        else:
            env_rider = os.getenv("TEST_RIDER_ID")
            if env_rider:
                rider_id = env_rider.strip()
                print(f"🔑 Using rider_id from TEST_RIDER_ID env: {rider_id}")
            else:
                print("🔎 No rider_id provided. Fetching one from 'riders' table...")
                # Try to get the most recently created rider
                try:
                    cur.execute("""
                        SELECT id
                        FROM riders
                        ORDER BY created_at DESC
                        LIMIT 1;
                    """)
                except Exception:
                    # Fallback if there is no created_at column
                    cur.execute("""
                        SELECT id
                        FROM riders
                        LIMIT 1;
                    """)

                row = cur.fetchone()
                if not row:
                    print("❌ No riders found in 'riders' table. Cannot insert bid.")
                    sys.exit(1)
                rider_id = row[0]
                print(f"✅ Auto-selected rider_id: {rider_id}")

        # ------------------------------
        # 2) Insert bid
        # ------------------------------
        sql = """
        INSERT INTO bids (
          ride_request_id,
          rider_id,
          price,
          status,
          expires_at
        ) VALUES (
          %s,
          %s,
          %s,
          'PENDING',
          NOW() + INTERVAL '1000 seconds'
        )
        RETURNING id, ride_request_id, rider_id, price, status, expires_at;
        """

        print(f"\n➡️  Inserting bid for ride_request_id={ride_request_id} with price={price} and rider_id={rider_id} ...")
        cur.execute(sql, (ride_request_id, rider_id, price))
        row = cur.fetchone()

        print("\n✅ Bid inserted:")
        print(f"  id              : {row[0]}")
        print(f"  ride_request_id : {row[1]}")
        print(f"  rider_id        : {row[2]}")
        print(f"  price           : {row[3]}")
        print(f"  status          : {row[4]}")
        print(f"  expires_at      : {row[5]}")

        cur.close()
    except Exception as e:
        print("❌ Error inserting bid:", e)
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
