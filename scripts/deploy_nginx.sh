#!/usr/bin/env bash
set -euo pipefail

STATIC_DIR=/var/www/medic
NGINX_SITE=/etc/nginx/sites-enabled/workmind
BUILD_DIR=/home/emanuele/workmind-v2/workmind-frontend/build

mkdir -p 
cp -r /. /
chown -R www-data:www-data  2>/dev/null || true
echo [ok] Frontend copiato in 

cp  .bak.1775756594

cat >  << 'NGINX'
limit_req_zone  zone=api_limit:10m rate=20r/s;

server {
    listen 100.116.199.50:80;
    server_name workmind-bender.tail898ef4.ts.net;
    return 301 https://;
}

server {
    listen 100.116.199.50:443 ssl http2;
    server_name workmind-bender.tail898ef4.ts.net;

    ssl_certificate     /etc/ssl/workmind/ts.crt;
    ssl_certificate_key /etc/ssl/workmind/ts.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_session_cache   shared:SSL:10m;

    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location /api/ {
        limit_req zone=api_limit burst=20 nodelay;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host ;
        proxy_set_header X-Real-IP ;
        proxy_set_header X-Forwarded-For ;
        proxy_set_header X-Forwarded-Proto ;
        proxy_read_timeout 120s;
    }

    location /_app/immutable/ {
        root /var/www/medic;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location / {
        root /var/www/medic;
        try_files  / /index.html;
        add_header Cache-Control "no-cache";
    }
}
NGINX

echo '[ok] nginx config aggiornata'
nginx -t && systemctl reload nginx
echo '[ok] nginx ricaricato'
echo ''
echo '=== Deploy completato ==='
echo 'URL: https://workmind-bender.tail898ef4.ts.net'
echo 'Login: medic1@ideasito.it / Medic2024!'
