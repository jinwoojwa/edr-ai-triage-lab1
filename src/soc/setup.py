"""인덱스 초기화: 텔레메트리 템플릿, 알림·리포트 인덱스. 여러 번 실행해도 안전합니다(멱등).

    python -m soc.setup
k3s에서는 setup Job으로 실행합니다 (인프라 6단계).
"""
from .alerts import ensure_indices
from .osclient import get_client
from .telemetry.index_template import apply_template


def main() -> None:
    client = get_client()
    apply_template(client)
    ensure_indices(client)
    print("인덱스 준비 완료: edr-events-* 템플릿, 알림, 리포트")


if __name__ == "__main__":
    main()
