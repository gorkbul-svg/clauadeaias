#!/bin/bash
# update_api_url.sh — Railway deploy sonrası demo.html'deki URL'i günceller
# Kullanım: bash update_api_url.sh https://bist-agent-xyz.railway.app

set -e
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

RAILWAY_URL=$1

if [ -z "$RAILWAY_URL" ]; then
  echo "Kullanım: bash update_api_url.sh https://RAILWAY_URL.railway.app"
  read -p "Railway URL'ini gir: " RAILWAY_URL
fi

# URL'den sondaki slash'ı kaldır
RAILWAY_URL="${RAILWAY_URL%/}"

echo ""
echo "🔧 API URL güncelleniyor..."
echo -e "   ${YELLOW}${RAILWAY_URL}${NC}"

# docs/demo.html içindeki placeholder'ı güncelle
sed -i "s|https://RAILWAY_URL_BURAYA.railway.app|${RAILWAY_URL}|g" \
  docs/demo.html docs/index.html 2>/dev/null || true

# macOS uyumlu versiyon (sed -i farklı çalışır)
sed -i '' "s|https://RAILWAY_URL_BURAYA.railway.app|${RAILWAY_URL}|g" \
  docs/demo.html docs/index.html 2>/dev/null || true

echo -e "${GREEN}✓ URL güncellendi${NC}"

# Git'e push et
echo ""
echo "📤 GitHub'a push ediliyor..."
git add docs/demo.html docs/index.html
git commit -m "config: Railway API URL güncellendi"
git push

echo ""
echo -e "${GREEN}✅ Tamamlandı!${NC}"
echo ""
echo "🌐 Demo: https://gorkbul-svg.github.io/clauadeaias/demo.html"
echo -e "⚡ API:  ${YELLOW}${RAILWAY_URL}${NC}"
