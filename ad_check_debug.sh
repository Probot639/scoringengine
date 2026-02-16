#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./ad_check_debug.sh [options]

Options:
  --host <ip>            AD host (default: 10.10.10.20)
  --port <port>          AD port (default: 389)
  --user <username>      AD username (default: sarasaka)
  --password <password>  AD password (default: Arasaka2077!)
  --domain <domain>      AD domain suffix (default: arasaka.com)
  --base-dn <dn>         LDAP base DN (default: DC=arasaka,DC=com)
  --fix-matcher          Update DB matching_content to "sAMAccountName: <user>"
  --fix-matcher-regex    Update DB matching_content to "sAMAccountName:\\s*<user>"
  --no-logs              Skip worker log output
  --help                 Show this help

Examples:
  ./ad_check_debug.sh
  ./ad_check_debug.sh --fix-matcher
  ./ad_check_debug.sh --fix-matcher-regex
  ./ad_check_debug.sh --user sarasaka --password 'Arasaka2077!'
EOF
}

HOST="10.10.10.20"
PORT="389"
USER_NAME="sarasaka"
PASSWORD="Arasaka2077!"
DOMAIN="arasaka.com"
BASE_DN="DC=arasaka,DC=com"
FIX_MATCHER=0
FIX_MATCHER_REGEX=0
SHOW_LOGS=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --user)
      USER_NAME="$2"
      shift 2
      ;;
    --password)
      PASSWORD="$2"
      shift 2
      ;;
    --domain)
      DOMAIN="$2"
      shift 2
      ;;
    --base-dn)
      BASE_DN="$2"
      shift 2
      ;;
    --fix-matcher)
      FIX_MATCHER=1
      shift
      ;;
    --fix-matcher-regex)
      FIX_MATCHER_REGEX=1
      shift
      ;;
    --no-logs)
      SHOW_LOGS=0
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if docker compose ps >/dev/null 2>&1; then
  DC=(docker compose)
elif sudo -n docker compose ps >/dev/null 2>&1; then
  DC=(sudo docker compose)
else
  DC=(sudo docker compose)
fi

run_mysql_query() {
  local query="$1"
  "${DC[@]}" exec -T mysql sh -lc 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -D scoring_engine' <<<"$query"
}

echo "== Docker service status =="
"${DC[@]}" ps

if [[ "$SHOW_LOGS" -eq 1 ]]; then
  echo
  echo "== Recent AD commands in worker logs =="
  "${DC[@]}" logs --no-log-prefix worker | grep "ActiveDirectoryCheck\|environment_id': 5\|ldapsearch -x -H ldap://" | tail -n 20 || true
fi

echo
echo "== Running LDAP bind/query from worker =="
"${DC[@]}" exec -T worker ldapsearch -x \
  -H "ldap://${HOST}:${PORT}" \
  -D "${USER_NAME}@${DOMAIN}" \
  -w "${PASSWORD}" \
  -b "${BASE_DN}" \
  '(objectclass=person)' sAMAccountName | tee /tmp/ad_check_debug_ldap.out

echo
echo "== Looking for target account in LDAP output =="
if grep -q "sAMAccountName: ${USER_NAME}" /tmp/ad_check_debug_ldap.out; then
  echo "Found: sAMAccountName: ${USER_NAME}"
else
  echo "Not found: sAMAccountName: ${USER_NAME}"
fi

echo
echo "== AD environment matcher in DB =="
run_mysql_query "
SELECT e.id, s.name, s.check_name, e.matching_content, HEX(e.matching_content) AS hex_mc
FROM environments e
JOIN services s ON s.id=e.service_id
WHERE s.check_name='ActiveDirectoryCheck';
"

if [[ "$FIX_MATCHER" -eq 1 ]]; then
  echo
  echo "== Applying matcher fix =="
  run_mysql_query "
UPDATE environments e
JOIN services s ON s.id=e.service_id
SET e.matching_content='sAMAccountName: ${USER_NAME}'
WHERE s.check_name='ActiveDirectoryCheck';
"
  echo "Updated matching_content to: sAMAccountName: ${USER_NAME}"
fi

if [[ "$FIX_MATCHER_REGEX" -eq 1 ]]; then
  echo
  echo "== Applying regex matcher fix (Python re syntax) =="
  run_mysql_query "
UPDATE environments e
JOIN services s ON s.id=e.service_id
SET e.matching_content='sAMAccountName:\\\\s*${USER_NAME}'
WHERE s.check_name='ActiveDirectoryCheck';
"
  echo "Updated matching_content to: sAMAccountName:\\s*${USER_NAME}"
fi

echo
echo "== AD environment matcher in DB (post-fix) =="
run_mysql_query "
SELECT e.id, s.name, s.check_name, e.matching_content, HEX(e.matching_content) AS hex_mc
FROM environments e
JOIN services s ON s.id=e.service_id
WHERE s.check_name='ActiveDirectoryCheck';
"

echo
echo "== Latest AD check results =="
run_mysql_query "
SELECT c.id, c.result, c.reason, c.command, LEFT(c.output, 300) AS output_snip
FROM checks c
JOIN services s ON s.id=c.service_id
WHERE s.check_name='ActiveDirectoryCheck'
ORDER BY c.id DESC
LIMIT 5;
"

echo
echo "Done."
