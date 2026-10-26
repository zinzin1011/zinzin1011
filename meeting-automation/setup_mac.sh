#!/bin/bash
# Mac 한 번에 설치: ./setup_mac.sh
set -e
cd "$(dirname "$0")"

if [ "$(uname -m)" != "arm64" ]; then
  echo "⚠️  Apple Silicon(M1 이상) Mac 이 아닙니다. mlx 대신 STT_BACKEND=local 을 쓰세요."
fi

if ! command -v brew >/dev/null; then
  echo "🍺 Homebrew 설치 (Mac 비밀번호를 물어보면 입력하세요)"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

echo "📦 ffmpeg, Python 설치"
brew install ffmpeg python@3.12

echo "🐍 가상환경 + 패키지 설치 (몇 분 걸립니다)"
"$(brew --prefix python@3.12)/bin/python3.12" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements-mac.txt
chmod +x mb

[ -f .env ] || { cp .env.example .env; sed -i '' 's/^STT_BACKEND=.*/STT_BACKEND=mlx/' .env; }
[ -f glossary.txt ] || cp glossary.example.txt glossary.txt

echo
echo "✅ 설치 완료. 이제 .env 와 glossary.txt 를 채우세요:"
echo "   open -e .env"
echo "   open -e glossary.txt"
echo "그다음 확인: ./mb record devices"
