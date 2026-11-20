"""Run periodically: python -m app.jobs.no_data [--now ISO8601 in TEST_MODE]."""
import argparse
from app.clock import parse_test_now, utc_now
from app.config import settings
from app.database import SessionLocal
from app.services.no_data_alerts import evaluate_no_data_alerts


def main():
    parser = argparse.ArgumentParser(description='Evaluate 24-hour no-data alerts')
    parser.add_argument('--now', help='TEST_MODE only: ISO8601 timestamp with offset')
    args = parser.parse_args()
    if args.now and not settings.test_mode:
        parser.error('--now requires TEST_MODE=1')
    now = parse_test_now(args.now) if args.now else utc_now()
    with SessionLocal() as db:
        count = evaluate_no_data_alerts(db, now)
        db.commit()
    print(f'No-data alerts created: {count}')


if __name__ == '__main__':
    main()
