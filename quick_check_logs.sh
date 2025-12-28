#!/bin/bash
# Quick one-liner to check Telegram /start logs

echo "Run this command on AWS server:"
echo ""
echo "docker-compose --profile aws logs --tail=200 backend-aws | grep -i 'TG.*START\|TG.*MENU\|TG.*ERROR' | tail -50"
echo ""
echo "Or for real-time monitoring:"
echo ""
echo "docker-compose --profile aws logs -f backend-aws | grep -i 'TG.*START\|TG.*MENU'"
echo ""










