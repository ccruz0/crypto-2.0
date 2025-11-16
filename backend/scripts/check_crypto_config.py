"""Script para verificar la configuración de Crypto.com Exchange"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def check_config():
    """Verificar configuración de Crypto.com"""
    print("\n" + "="*60)
    print("🔍 Verificando Configuración de Crypto.com Exchange")
    print("="*60 + "\n")
    
    use_proxy = os.getenv("USE_CRYPTO_PROXY", "true").lower() == "true"
    live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
    api_key = os.getenv("EXCHANGE_CUSTOM_API_KEY", "")
    api_secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET", "")
    
    print("📋 Configuración Actual:")
    print(f"  • USE_CRYPTO_PROXY: {use_proxy}")
    print(f"  • LIVE_TRADING: {live_trading}")
    print(f"  • API Key: {'✅ Configurada' if api_key else '❌ No configurada'}")
    print(f"  • API Secret: {'✅ Configurada' if api_secret else '❌ No configurada'}")
    print()
    
    if use_proxy:
        proxy_url = os.getenv("CRYPTO_PROXY_URL", "http://127.0.0.1:9000")
        proxy_token = os.getenv("CRYPTO_PROXY_TOKEN", "")
        print(f"  • Proxy URL: {proxy_url}")
        print(f"  • Proxy Token: {'✅ Configurado' if proxy_token else '❌ No configurado'}")
    else:
        base_url = os.getenv("EXCHANGE_CUSTOM_BASE_URL", "https://api.crypto.com/exchange/v1")
        print(f"  • Base URL: {base_url}")
    
    print()
    
    # Verificar configuración válida
    issues = []
    recommendations = []
    
    if use_proxy and not live_trading:
        issues.append("⚠️  Usando proxy pero LIVE_TRADING=false (modo dry-run)")
    
    if not use_proxy and not live_trading:
        print("✅ Configuración: Modo Dry-Run (datos simulados)")
        print("   Esto es correcto para testing sin conexión real")
        return
    
    if not use_proxy and live_trading:
        if not api_key or not api_secret:
            issues.append("❌ Conexión directa habilitada pero faltan API credentials")
            recommendations.append("   Configura EXCHANGE_CUSTOM_API_KEY y EXCHANGE_CUSTOM_API_SECRET")
        else:
            print("✅ Configuración: Conexión directa a Crypto.com Exchange")
            recommendations.append("   Asegúrate de que tu IP esté whitelisted en Crypto.com")
    
    if use_proxy and live_trading:
        if not api_secret:
            issues.append("⚠️  Proxy configurado pero falta PROXY_TOKEN")
        print("✅ Configuración: Conexión a través de proxy")
        recommendations.append("   Asegúrate de que el proxy esté corriendo")
    
    if issues:
        print("⚠️  Problemas detectados:")
        for issue in issues:
            print(f"  {issue}")
        print()
    
    if recommendations:
        print("💡 Recomendaciones:")
        for rec in recommendations:
            print(f"  {rec}")
        print()
    
    print("="*60 + "\n")

if __name__ == "__main__":
    check_config()
