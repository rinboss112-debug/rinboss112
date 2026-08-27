from __future__ import annotations

import argparse
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from cloud_storage import DRIVE_FILE_SCOPE
from google_sheet_search import SHEETS_READONLY_SCOPE


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tạo cấu hình Google Drive + Google Sheets OAuth cho Streamlit Secrets."
    )
    parser.add_argument(
        "--client-secrets",
        type=Path,
        default=Path("client_secret.json"),
        help="File OAuth Desktop client tải từ Google Cloud Console.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("drive_secrets.toml"),
    )
    parser.add_argument(
        "--folder-name",
        default="Amazon Product Scraper",
    )
    return parser


def run_oauth_setup() -> int:
    args = build_parser().parse_args()
    if not args.client_secrets.exists():
        raise SystemExit(f"Không tìm thấy file: {args.client_secrets}")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(args.client_secrets), scopes=[DRIVE_FILE_SCOPE, SHEETS_READONLY_SCOPE]
    )
    credentials = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
        open_browser=True,
    )
    if not credentials.refresh_token:
        raise SystemExit(
            "Google không trả refresh token. Hãy thu hồi quyền ứng dụng rồi chạy lại."
        )

    content = "\n".join(
        (
            "[google_drive]",
            f"client_id = {_toml_string(credentials.client_id or '')}",
            f"client_secret = {_toml_string(credentials.client_secret or '')}",
            f"refresh_token = {_toml_string(credentials.refresh_token)}",
            f"folder_name = {_toml_string(args.folder_name)}",
            "",
        )
    )
    args.output.write_text(content, encoding="utf-8")
    print(f"Đã tạo {args.output}.")
    print("Hãy sao chép nội dung file này vào Streamlit → App settings → Secrets.")
    print("Không commit file này lên GitHub.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_oauth_setup())
