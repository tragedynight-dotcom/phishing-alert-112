"""VAPID 키 생성 (Web Push용). secrets.toml 에 넣을 값을 출력합니다."""

from __future__ import annotations


def main() -> None:
    try:
        from py_vapid import Vapid02 as Vapid
    except ImportError:  # pragma: no cover
        from py_vapid import Vapid01 as Vapid

    vapid = Vapid()
    vapid.generate_keys()

    public_key = vapid.public_key
    private_key = vapid.private_key
    if isinstance(public_key, bytes):
        public_key = public_key.decode("utf-8")
    if isinstance(private_key, bytes):
        private_key = private_key.decode("utf-8")

    print("아래 값을 .streamlit/secrets.toml 에 추가하세요.\n")
    print(f'VAPID_PUBLIC_KEY = "{public_key}"')
    print(f'VAPID_PRIVATE_KEY = "{private_key}"')
    print('VAPID_CLAIMS_EMAIL = "mailto:your-email@example.com"')


if __name__ == "__main__":
    main()
