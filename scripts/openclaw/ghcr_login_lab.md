# Login GHCR en LAB sin escribir el token

El token se guarda una vez en AWS Parameter Store. En LAB solo ejecutas un comando (sin pegar nada).

---

## Una vez (en tu Mac)

Pon el token en una variable y guárdalo en Parameter Store:

```bash
export GHCR_TOKEN='ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
aws ssm put-parameter \
  --name /openclaw/ghcr-token \
  --value "$GHCR_TOKEN" \
  --type SecureString \
  --region ap-southeast-1 \
  --overwrite
```

(Usa tu PAT real; el de arriba es solo formato. Puedes crearlo en GitHub → Settings → Developer settings → Personal access tokens, con scope `read:packages`.)

---

## Una vez en LAB: instalar AWS CLI v2 (si no está)

En Ubuntu 24.04 el paquete `awscli` de apt no suele estar. Instala la CLI v2 oficial:

```bash
curl -sS "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
sudo apt-get install -y unzip
unzip -o /tmp/awscliv2.zip -d /tmp
sudo /tmp/aws/install
rm -rf /tmp/aws /tmp/awscliv2.zip
```

## Cada vez que entres a LAB por SSM

Conéctate y haz el login con el parámetro:

```bash
aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1
```

Dentro de LAB:

```bash
aws ssm get-parameter --name /openclaw/ghcr-token --with-decryption --query Parameter.Value --output text --region ap-southeast-1 | sudo docker login ghcr.io -u ccruz0 --password-stdin
```

No pide password: el token sale del parameter y se pasa a `docker login`.

---

## Si LAB no tiene permiso para GetParameter

El rol de la instancia LAB (p. ej. `atp-lab-ssm-role` o `EC2_SSM_Role`) debe poder leer el parámetro. Si al ejecutar el comando anterior ves un error de acceso, añade al rol una policy como:

```json
{
  "Effect": "Allow",
  "Action": ["ssm:GetParameter", "ssm:GetParameters"],
  "Resource": "arn:aws:ssm:ap-southeast-1:YOUR_ACCOUNT_ID:parameter/openclaw/*"
}
```

Sustituye `YOUR_ACCOUNT_ID` por el ID de tu cuenta AWS.
