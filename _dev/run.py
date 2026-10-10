import argparse
import hashlib
import io
import os
import subprocess
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
HIDDEN = (".", "_", "#")

RELOAD = b"""
<script>
(() => {
  const version = "VERSION";
  setInterval(async () => {
    try {
      const response = await fetch("/__dev_version", {cache: "no-store"});
      if (response.ok && await response.text() !== version) {
        location.reload();
      }
    } catch {}
  }, 1000);
})();
</script>
"""


def version() -> str:
    digest = hashlib.sha256()
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if not d.startswith(HIDDEN))
        for name in sorted(files):
            if name.startswith(HIDDEN):
                continue
            path = Path(folder) / name
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            digest.update(
                f"{path.relative_to(ROOT)}:{stat.st_mtime_ns}:{stat.st_size}\n".encode()
            )
    return digest.hexdigest()


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format, *args):
        if urlsplit(self.path).path != "/__dev_version":
            super().log_message(format, *args)

    def send_head(self):
        request_path = urlsplit(self.path).path
        if request_path == "/__dev_version":
            body = version().encode()
            content_type = "text/plain"
        else:
            path = Path(self.translate_path(self.path))
            if path.is_dir():
                if not request_path.endswith("/"):
                    return super().send_head()
                path /= "index.html"

            if path.suffix.lower() not in (".html", ".htm") or not path.is_file():
                return super().send_head()

            try:
                body = path.read_bytes()
            except OSError:
                return super().send_head()

            script = RELOAD.replace(b"VERSION", version().encode())
            body = (
                body.replace(b"</body>", script + b"</body>", 1)
                if b"</body>" in body
                else body + script
            )
            content_type = "text/html; charset=utf-8"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        return io.BytesIO(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("dev", "build"))
    args = parser.parse_args()

    os.chdir(ROOT)
    (ROOT / "assets").mkdir(exist_ok=True)
    command = [
        str(ROOT / "_dev" / "tailwindcss"),
        "-i",
        str(ROOT / "_dev" / "input.css"),
        "-o",
        str(ROOT / "assets" / "styles.css"),
    ]

    if args.command == "build":
        subprocess.run(command + ["--minify"], check=True)
        print("Built assets/styles.css")
        return

    with ThreadingHTTPServer(("127.0.0.1", 8000), Handler) as server:
        server.timeout = 0.5
        watcher = subprocess.Popen(
            command + ["--watch=always"],
            start_new_session=True,
        )
        try:
            print("Open http://127.0.0.1:8000 — Ctrl+C to stop.", flush=True)
            while watcher.poll() is None:
                server.handle_request()
            raise SystemExit(watcher.returncode)
        finally:
            if watcher.poll() is None:
                watcher.terminate()
            try:
                watcher.wait(timeout=5)
            except subprocess.TimeoutExpired:
                watcher.kill()
                watcher.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
