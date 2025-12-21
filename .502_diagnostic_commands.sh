#!/bin/bash
# Comandos de diagnóstico 502 - Ejecuta estos comandos en la terminal de Cursor (⌘+J)
# O ejecuta este archivo completo: bash .502_diagnostic_commands.sh

bash scripts/debug_dashboard_remote.sh
ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws ps frontend-aws'
ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws up -d frontend-aws'
ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws restart && sudo systemctl restart nginx'
ssh hilovivo-aws 'sudo systemctl restart nginx'
ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws restart backend-aws'
ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws logs --tail=50 frontend-aws'
ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws logs --tail=50 backend-aws'
