// Copie para segredos.h (que NÃO vai para o git) e preencha.
#pragma once

// Rede do estande: o ESP32 e o NOTEBOOK do backend na MESMA rede 2,4 GHz
// (o ESP32 não enxerga 5 GHz). Hotspot do celular serve.
#define WIFI_SSID   "NOME_DA_REDE"
#define WIFI_SENHA  "SENHA_DA_REDE"

// IP do NOTEBOOK que roda o uvicorn, nessa rede, SEM barra no fim e sem
// caminho depois da porta (a assinatura usa o caminho /hardware/v2/...).
// Descubra com `ipconfig` (Adaptador Wi-Fi > Endereço IPv4).
// Suba o backend com:  uvicorn main:app --host 0.0.0.0 --port 8000
// Não use localhost: para o ESP32, localhost é ele mesmo.
// No hotspot do Windows o notebook é sempre 192.168.137.1.
#define BACKEND_URL "http://192.168.137.1:8000"

// Saem de, dentro de backend/:  python preparar_totem.py --next
// (a chave é derivada da DEVICE_MASTER_KEY do backend/.env: trocou a chave
// mestra ou o notebook usa outro .env -> rode de novo e grave de novo).
#define DEVICE_ID      "00000000-0000-0000-0000-000000000000"
#define DEVICE_KEY_HEX "64_caracteres_hexadecimais"
