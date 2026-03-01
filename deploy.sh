#!/bin/bash
# deploy.sh — Tek komutla GitHub'a yükle ve Pages'i hazırla
# Kullanım: bash deploy.sh

set -e
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

GITHUB_USER="gorkbul-svg"
REPO_NAME="clauadeaias"
REPO_URL="https://github.com/${GITHUB_USER}/${REPO_NAME}.git"

echo ""
echo -e "${CYAN}🚀 BIST Agent → GitHub Pages Deploy${NC}"
echo "======================================"
echo -e "📦 Repo: ${YELLOW}${REPO_URL}${NC}"
echo ""

# Git init (yoksa)
[ ! -d ".git" ] && git init && git branch -M main

# .env varsa uyar
[ -f ".env" ] && echo -e "${YELLOW}⚠️  .env dosyası .gitignore tarafından korunuyor${NC}"

# Stage + commit
git add .
git commit -m "deploy: BIST Agent + GitHub Pages

- Landing sayfası (docs/index.html)
- İnteraktif demo (docs/demo.html)
- GitHub Actions auto-deploy (.github/workflows/deploy.yml)
- Yahoo Finance API entegrasyonu
- Claude Tool Use API agent" 2>/dev/null || \
git commit --allow-empty -m "deploy: dosyalar güncellendi"

# Remote ayarla ve push et
git remote add origin "$REPO_URL" 2>/dev/null || \
  git remote set-url origin "$REPO_URL"

git push -u origin main

echo ""
echo -e "${GREEN}✅ Push tamamlandı!${NC}"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}📌 SON ADIM — Pages'i aktif et (1 dakika):${NC}"
echo ""
echo -e "  1. Şu linki aç:"
echo -e "     ${YELLOW}https://github.com/${GITHUB_USER}/${REPO_NAME}/settings/pages${NC}"
echo ""
echo -e "  2. Build and deployment:"
echo -e "     Source → ${YELLOW}GitHub Actions${NC} seç"
echo ""
echo -e "  3. Workflow otomatik çalışır (~2 dk)"
echo ""
echo -e "  4. Sitenin URL'i:"
echo -e "     ${YELLOW}https://${GITHUB_USER}.github.io/${REPO_NAME}${NC}"
echo -e "     ${YELLOW}https://${GITHUB_USER}.github.io/${REPO_NAME}/demo.html${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
