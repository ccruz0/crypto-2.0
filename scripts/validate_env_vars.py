#!/usr/bin/env python3
"""
Script para validar que todas las variables de entorno requeridas estén configuradas.
Este script verifica que no haya credenciales hardcodeadas y que todas las variables
requeridas estén presentes en los archivos .env apropiados.
"""

import os
import sys
from pathlib import Path
from typing import List, Dict

# Variables requeridas por entorno
REQUIRED_VARS = {
    "common": [
        "POSTGRES_PASSWORD",
        "SECRET_KEY",
    ],
    "aws": [
        "OPENVPN_USER",
        "OPENVPN_PASSWORD",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "CRYPTO_API_KEY",
        "CRYPTO_API_SECRET",
        "CRYPTO_PROXY_TOKEN",
    ],
    "local": [
        # Variables opcionales para desarrollo local
    ],
}

# Valores inseguros que no deben usarse
INSECURE_DEFAULTS = [
    "your-secret-key-here",
    "traderpass",
    "CHANGE_ME",
    "CHANGE_ME_STRONG_PASSWORD_64",
    "TODO",
    "REPLACE_ME",
    "demo-key",
    "",
]

# Variables que pueden estar solo en el servidor AWS (no en el repo local)
AWS_ONLY_VARS = [
    "OPENVPN_USER",
    "OPENVPN_PASSWORD",
    "CRYPTO_API_KEY",
    "CRYPTO_API_SECRET",
    "CRYPTO_PROXY_TOKEN",
]


def check_hardcoded_credentials(file_path: Path) -> List[str]:
    """Buscar credenciales hardcodeadas en un archivo"""
    issues = []
    
    if not file_path.exists():
        return issues
    
    with open(file_path, 'r') as f:
        content = f.read()
        lines = content.split('\n')
    
    # Patrones a buscar
    patterns = [
        ("OPENVPN_USER=", "OPENVPN_USER"),
        ("OPENVPN_PASSWORD=", "OPENVPN_PASSWORD"),
        ("TELEGRAM_BOT_TOKEN=", "TELEGRAM_BOT_TOKEN"),
        ("TELEGRAM_CHAT_ID=", "TELEGRAM_CHAT_ID"),
    ]
    
    for i, line in enumerate(lines, 1):
        for pattern, var_name in patterns:
            if pattern in line and "${" not in line:
                # Verificar que no sea un comentario
                stripped = line.strip()
                if not stripped.startswith('#'):
                    issues.append(f"Línea {i}: {var_name} parece estar hardcodeado")
    
    return issues


def validate_env_file(env_file: Path, required_vars: List[str]) -> Dict[str, any]:
    """Validar que un archivo .env tenga todas las variables requeridas"""
    result = {
        "exists": False,
        "missing": [],
        "insecure": [],
        "valid": False,
    }
    
    if not env_file.exists():
        result["exists"] = False
        result["missing"] = required_vars.copy()
        return result
    
    result["exists"] = True
    
    with open(env_file, 'r') as f:
        content = f.read()
    
    # Verificar variables requeridas
    for var in required_vars:
        if f"{var}=" not in content:
            result["missing"].append(var)
        else:
            # Verificar valores inseguros
            for line in content.split('\n'):
                if line.startswith(f"{var}="):
                    value = line.split('=', 1)[1].strip().strip('"').strip("'")
                    if value in INSECURE_DEFAULTS:
                        result["insecure"].append(var)
                    break
    
    result["valid"] = len(result["missing"]) == 0 and len(result["insecure"]) == 0
    return result


def check_var_in_all_env_files(var_name: str, env_files: List[Path]) -> tuple[bool, Path, bool]:
    """Verificar si una variable existe en alguno de los archivos .env
    Returns: (found, env_file, is_insecure)
    """
    for env_file in env_files:
        if env_file.exists():
            with open(env_file, 'r') as f:
                content = f.read()
                if f"{var_name}=" in content:
                    # Verificar el valor
                    for line in content.split('\n'):
                        if line.startswith(f"{var_name}="):
                            value = line.split('=', 1)[1].strip().strip('"').strip("'")
                            is_insecure = value in INSECURE_DEFAULTS
                            return True, env_file, is_insecure
    return False, None, False


def main():
    """Función principal"""
    base_dir = Path(__file__).parent.parent
    env_aws = base_dir / ".env.aws"
    env_local = base_dir / ".env.local"
    env_base = base_dir / ".env"
    docker_compose = base_dir / "docker-compose.yml"
    
    # Lista de archivos .env a verificar (docker-compose.yml carga de todos)
    all_env_files = [env_base, env_local, env_aws]
    
    print("🔍 Validando configuración de variables de entorno...")
    print("   (docker-compose.yml carga de: .env, .env.local, .env.aws)\n")
    
    # 1. Verificar credenciales hardcodeadas en docker-compose.yml
    print("1️⃣ Verificando credenciales hardcodeadas en docker-compose.yml...")
    docker_issues = check_hardcoded_credentials(docker_compose)
    if docker_issues:
        print("   ❌ Problemas encontrados:")
        for issue in docker_issues:
            print(f"      - {issue}")
    else:
        print("   ✅ No se encontraron credenciales hardcodeadas")
    print()
    
    # 2. Validar variables requeridas (buscando en todos los archivos .env)
    print("2️⃣ Validando variables requeridas (buscando en .env, .env.local, .env.aws)...")
    aws_vars = REQUIRED_VARS["common"] + REQUIRED_VARS["aws"]
    missing_vars = []
    insecure_vars = []
    found_vars = {}
    
    for var in aws_vars:
        found, env_file, is_insecure = check_var_in_all_env_files(var, all_env_files)
        if found:
            found_vars[var] = env_file.name
            if is_insecure:
                insecure_vars.append(var)
                print(f"   ⚠️  {var} encontrado en {env_file.name} pero con valor inseguro")
            else:
                print(f"   ✅ {var} encontrado en {env_file.name}")
        else:
            if var in AWS_ONLY_VARS:
                print(f"   ⚠️  {var} no encontrado (puede estar solo en servidor AWS)")
            else:
                missing_vars.append(var)
                print(f"   ❌ {var} NO encontrado en ningún archivo .env")
    
    # Ya verificamos valores inseguros arriba, solo mostramos resumen si hay
    
    print()
    
    # 3. Resumen de archivos .env
    print("3️⃣ Archivos .env encontrados:")
    for env_file in all_env_files:
        if env_file.exists():
            var_count = len([line for line in open(env_file).readlines() if '=' in line and not line.strip().startswith('#')])
            print(f"   ✅ {env_file.name} ({var_count} variables)")
        else:
            print(f"   ⚠️  {env_file.name} no existe")
    print()
    
    # Resumen final
    print("=" * 60)
    all_valid = (
        len(docker_issues) == 0 and
        len(missing_vars) == 0 and
        len(insecure_vars) == 0
    )
    
    if all_valid:
        print("✅ Validación exitosa - Todo está correctamente configurado")
        print("\n📊 Resumen:")
        print(f"   - Variables encontradas: {len(found_vars)}/{len(aws_vars)}")
        if found_vars:
            print("   - Ubicaciones:")
            for var, file in found_vars.items():
                print(f"     • {var} → {file}")
        return 0
    else:
        print("⚠️  Validación con advertencias - Revisa los problemas arriba")
        if missing_vars:
            print(f"\n❌ Variables faltantes ({len(missing_vars)}):")
            print("   (Agregar a cualquiera de: .env, .env.local, o .env.aws)")
            for var in missing_vars:
                print(f"   - {var}")
        if insecure_vars:
            print(f"\n⚠️  Variables con valores inseguros ({len(insecure_vars)}):")
            for var in insecure_vars:
                print(f"   - {var} (en .env.aws)")
        print("\n📋 Próximos pasos:")
        if missing_vars:
            print("   1. Agregar variables faltantes a algún archivo .env")
        if insecure_vars:
            print("   2. Reemplazar valores inseguros con valores seguros")
        print("   3. Ver FIXES_CRITICOS_SEGURIDAD.md para más detalles")
        return 1


if __name__ == "__main__":
    sys.exit(main())

