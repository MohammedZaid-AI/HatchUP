import os
import shutil
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT_DIR / "templates"
STATIC_DIR = ROOT_DIR / "static"
DIST_DIR = ROOT_DIR / "netlify_dist"

BACKEND_ORIGIN_ENV = "HATCHUP_BACKEND_ORIGIN"
SUPABASE_URL_ENV = "SUPABASE_URL"
SUPABASE_ANON_KEY_ENV = "SUPABASE_ANON_KEY"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def clean_dist() -> None:
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True, exist_ok=True)


def render_template(source_name: str) -> str:
    content = read_text(TEMPLATES_DIR / source_name)
    content = content.replace(
        "{{ supabase_url | default('', true) | e }}",
        os.environ.get(SUPABASE_URL_ENV, ""),
    )
    content = content.replace(
        "{{ supabase_anon_key | default('', true) | e }}",
        os.environ.get(SUPABASE_ANON_KEY_ENV, ""),
    )
    return content


def require_backend_origin() -> str:
    backend_origin = os.environ.get(BACKEND_ORIGIN_ENV, "").strip().rstrip("/")
    if not backend_origin:
        raise SystemExit(
            f"Missing required environment variable: {BACKEND_ORIGIN_ENV}. "
            "Set it to your deployed FastAPI backend origin, for example "
            "https://your-backend.onrender.com"
        )
    return backend_origin


def copy_static_assets() -> None:
    shutil.copytree(STATIC_DIR, DIST_DIR / "static")


def write_static_pages() -> None:
    write_text(DIST_DIR / "index.html", render_template("home.html"))
    write_text(DIST_DIR / "privacy" / "index.html", render_template("privacy.html"))
    write_text(DIST_DIR / "terms" / "index.html", render_template("terms.html"))


def write_redirects(backend_origin: str) -> None:
    redirects = f"""\
/dashboard {backend_origin}/dashboard 200
/vc {backend_origin}/vc 200
/vc/* {backend_origin}/vc/:splat 200
/founder {backend_origin}/founder 200
/founder-mode {backend_origin}/founder-mode 200
/founder/* {backend_origin}/founder/:splat 200
/talent-scout {backend_origin}/talent-scout 200
/chat {backend_origin}/chat 200
/research {backend_origin}/research 200
/hatchup_chat {backend_origin}/hatchup_chat 200
/api/* {backend_origin}/api/:splat 200
/healthz {backend_origin}/healthz 200
"""
    write_text(DIST_DIR / "_redirects", redirects)


def main() -> None:
    backend_origin = require_backend_origin()
    clean_dist()
    copy_static_assets()
    write_static_pages()
    write_redirects(backend_origin)
    print(f"Netlify build output created in {DIST_DIR}")


if __name__ == "__main__":
    main()
