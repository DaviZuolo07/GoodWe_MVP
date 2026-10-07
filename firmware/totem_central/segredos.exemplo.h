// Copie para segredos.h (que NÃO vai para o git) e preencha.
#pragma once

#define WIFI_SSID   "NOME_DA_REDE"
#define WIFI_SENHA  "SENHA_DA_REDE"

// IP do computador que roda o uvicorn, na mesma rede, SEM barra no fim e sem
// caminho depois da porta (a assinatura usa o caminho /hardware/v2/...).
// Suba o backend com:  uvicorn main:app --host 0.0.0.0 --port 8000
// Não use localhost: para o ESP32, localhost é ele mesmo.
#define BACKEND_URL "http://192.168.0.100:8000"

// Saem de, dentro de backend/:  python preparar_totem.py --fisico --sem-env
// (copie DEVICE_ID e DEVICE_KEY_HEX da saída; a chave chega por canal privado).
#define DEVICE_ID      "00000000-0000-0000-0000-000000000000"
#define DEVICE_KEY_HEX "64_caracteres_hexadecimais"
