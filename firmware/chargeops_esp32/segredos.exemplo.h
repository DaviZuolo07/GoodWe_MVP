#pragma once

const char* WIFI_SSID  = "NOME_DA_SUA_REDE";
const char* WIFI_SENHA = "SENHA_DA_REDE";

// IP da máquina que roda o uvicorn, na mesma rede. Descubra com `ipconfig`
// (Windows) ou `ip addr` (Linux/Mac). NÃO use localhost: para o ESP32,
// localhost é ele mesmo. Suba o backend com --host 0.0.0.0.
const char* BACKEND_URL = "http://192.168.0.100:8000";

// Gere com, de dentro de backend/:
//   python provisionar.py token-esp --carregador <uuid-do-carregador>
// O banco guarda só o hash: este texto aparece uma única vez.
const char* DEVICE_TOKEN = "sua_chave";
