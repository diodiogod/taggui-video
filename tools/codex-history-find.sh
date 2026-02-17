#!/usr/bin/env bash
set -euo pipefail

history_file="${CODEX_HISTORY_FILE:-$HOME/.codex/history.jsonl}"
current_id="${CODEX_THREAD_ID:-}"
include_current=0
ids_only=0
limit=20
mode="terms"

usage() {
  cat <<'USAGE'
Search Codex history and return matching session IDs.

Usage:
  codex-history-find.sh [options] <query text>

Options:
  -n, --limit <N>         Max number of sessions to return (default: 20)
  -f, --history <FILE>    History file (default: ~/.codex/history.jsonl)
  -c, --current-id <ID>   Current session ID to exclude (default: $CODEX_THREAD_ID)
      --include-current   Include current session in results
      --phrase            Match exact phrase (case-insensitive substring)
      --regex             Match regex (case-insensitive, jq regex syntax)
      --ids-only          Print only session IDs
  -h, --help              Show this help

Examples:
  codex-history-find.sh "video still plays instantly"
  codex-history-find.sh --ids-only "windows terminal codex"
  codex-history-find.sh --phrase "exact words in order"
  codex-history-find.sh --regex "video.*pause"
  codex-history-find.sh --include-current "search exact conversations"
USAGE
}

require_arg() {
  local flag="$1"
  local value="${2:-}"
  if [[ -z "$value" ]]; then
    echo "Missing value for $flag" >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--limit)
      require_arg "$1" "${2:-}"
      limit="$2"
      shift 2
      ;;
    -f|--history)
      require_arg "$1" "${2:-}"
      history_file="$2"
      shift 2
      ;;
    -c|--current-id)
      require_arg "$1" "${2:-}"
      current_id="$2"
      shift 2
      ;;
    --include-current)
      include_current=1
      shift
      ;;
    --phrase)
      mode="phrase"
      shift
      ;;
    --regex)
      mode="regex"
      shift
      ;;
    --ids-only)
      ids_only=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -eq 0 ]]; then
  echo "Query text is required." >&2
  usage >&2
  exit 1
fi

if [[ ! "$limit" =~ ^[0-9]+$ ]]; then
  echo "--limit must be a non-negative integer." >&2
  exit 1
fi

if [[ ! -f "$history_file" ]]; then
  echo "History file not found: $history_file" >&2
  exit 1
fi

query="$*"
terms_json="$(printf '%s' "$query" | jq -R 'ascii_downcase | split(" ") | map(select(length > 0))')"

if [[ "$ids_only" -eq 1 ]]; then
  jq -rs \
    --arg q "$query" \
    --arg mode "$mode" \
    --argjson terms "$terms_json" \
    --arg current "$current_id" \
    --argjson include_current "$include_current" \
    --argjson limit "$limit" '
    def matches_query:
      if $mode == "phrase" then
        (.text | ascii_downcase | contains($q | ascii_downcase))
      elif $mode == "regex" then
        (.text | test($q; "i"))
      else
        (.text | ascii_downcase) as $t
        | ($terms | length) > 0 and
          (all($terms[]; $t | contains(.)))
      end;
    map(select(type == "object" and .session_id? and .text? and .ts?))
    | map(select(matches_query))
    | map(select($include_current == 1 or $current == "" or .session_id != $current))
    | group_by(.session_id)
    | map({session_id: .[0].session_id, last_ts: (map(.ts) | max)})
    | sort_by(.last_ts) | reverse
    | .[:$limit]
    | .[].session_id
    ' "$history_file"
  exit 0
fi

matches="$(jq -rs \
  --arg q "$query" \
  --arg mode "$mode" \
  --argjson terms "$terms_json" \
  --arg current "$current_id" \
  --argjson include_current "$include_current" \
  --argjson limit "$limit" '
  def matches_query:
    if $mode == "phrase" then
      (.text | ascii_downcase | contains($q | ascii_downcase))
    elif $mode == "regex" then
      (.text | test($q; "i"))
    else
      (.text | ascii_downcase) as $t
      | ($terms | length) > 0 and
        (all($terms[]; $t | contains(.)))
    end;
  map(select(type == "object" and .session_id? and .text? and .ts?))
  | map(select(matches_query))
  | map(select($include_current == 1 or $current == "" or .session_id != $current))
  | group_by(.session_id)
  | map({
      session_id: .[0].session_id,
      hits: length,
      last_ts: (map(.ts) | max),
      last_iso: ((map(.ts) | max) | todateiso8601),
      sample: ((sort_by(.ts) | last | .text) | gsub("[\\r\\n\\t]"; " "))
    })
  | sort_by(.last_ts) | reverse
  | .[:$limit]
  | .[]
  | "\(.session_id)\t\(.hits)\t\(.last_iso)\t\(.sample[0:140])"
  ' "$history_file")"

if [[ -z "$matches" ]]; then
  echo "No matches for query: $query" >&2
  exit 2
fi

printf "session_id\thits\tlast_message_utc\tsample\n"
printf '%s\n' "$matches"
