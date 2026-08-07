#!/usr/bin/env bash
# ===========================================================================
# NodeLinker local dev helper
#
# Usage:
#   ./dev/local.sh start              # 전체 서비스 시작 + Vault 시드
#   ./dev/local.sh stop               # 전체 서비스 중지
#   ./dev/local.sh restart            # 전체 재시작 + Vault 시드
#   ./dev/local.sh restart backend    # 백엔드만 재시작
#   ./dev/local.sh restart celery     # celery-worker + celery-beat 재시작
#   ./dev/local.sh restart frontend   # nginx 이미지 재빌드 후 재시작 (프론트엔드 변경 시)
#   ./dev/local.sh restart nodes      # 테스트 노드만 재시작 + Vault 시드
#   ./dev/local.sh seed               # Vault 시드만 재실행 (노드 재등록)
#   ./dev/local.sh logs [service]     # 로그 출력 (기본: backend)
#   ./dev/local.sh status             # 컨테이너 상태 확인
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE="docker compose -f $PROJECT_ROOT/docker-compose.yml -f $PROJECT_ROOT/docker-compose.dev.yml"

# Vault가 데이터를 갖고 있는지 확인
_vault_has_data() {
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "X-Vault-Token: ${VAULT_TOKEN:-nodelinker-dev-token}" \
        http://localhost:8200/v1/secret/data/ansible/test-node 2>/dev/null || true)
    [ "$status" = "200" ]
}

# 인프라 서비스(db/redis/vault)가 healthy 상태가 될 때까지 대기
_wait_healthy() {
    echo "인프라 서비스 준비 대기 중..."
    local max=30 count=0
    until $COMPOSE ps db redis vault 2>/dev/null | grep -q "healthy"; do
        sleep 2
        count=$((count + 1))
        if [ "$count" -ge "$max" ]; then
            echo "✗ 타임아웃: 인프라 서비스가 healthy 상태가 되지 않았습니다." >&2
            exit 1
        fi
    done
    echo "  → 인프라 ready"
}

_seed() {
    echo "Vault 시드 실행 중..."
    bash "$SCRIPT_DIR/seed-local.sh"
}

_cmd="${1:-help}"
shift || true

case "$_cmd" in

    start)
        echo "=== 서비스 시작 ==="
        $COMPOSE up -d
        _wait_healthy
        if ! _vault_has_data; then
            _seed
        else
            echo "Vault 데이터 확인됨 — 시드 생략"
        fi
        echo ""
        echo "  Web UI:  http://localhost:8888"
        echo "  API:     http://localhost:8000/api/docs"
        echo "  Vault:   http://localhost:8200  (token: nodelinker-dev-token)"
        ;;

    stop)
        echo "=== 서비스 중지 ==="
        $COMPOSE stop
        ;;

    restart)
        target="${1:-all}"
        case "$target" in
            backend)
                echo "=== 백엔드 재시작 ==="
                $COMPOSE restart backend
                ;;
            celery)
                echo "=== Celery 재시작 ==="
                $COMPOSE restart celery-worker celery-beat
                ;;
            frontend)
                echo "=== 프론트엔드 빌드 및 재시작 ==="
                $COMPOSE build nginx
                $COMPOSE up -d nginx
                ;;
            nodes)
                echo "=== 테스트 노드 재시작 ==="
                $COMPOSE restart test-node test-node-2
                _wait_healthy
                _seed
                ;;
            all)
                echo "=== 전체 재시작 ==="
                $COMPOSE restart
                _wait_healthy
                # Vault는 dev 모드라 재시작 시 데이터 초기화됨 → 항상 시드
                _seed
                ;;
            *)
                echo "알 수 없는 대상: $target" >&2
                echo "사용법: $0 restart [backend|celery|frontend|nodes|all]" >&2
                exit 1
                ;;
        esac
        ;;

    seed)
        _seed
        ;;

    logs)
        service="${1:-backend}"
        $COMPOSE logs -f "$service"
        ;;

    status)
        $COMPOSE ps
        ;;

    help|--help|-h)
        sed -n '/^# Usage:/,/^# ====/p' "$0" | grep -v "^#\s*====" | sed 's/^# //'
        ;;

    *)
        echo "알 수 없는 명령: $_cmd" >&2
        echo "도움말: $0 help" >&2
        exit 1
        ;;
esac
