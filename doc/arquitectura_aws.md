# Diseño Técnico — Sistema Multi-Agente de Cobranza

**Candidato**: Esteban (AI Developer)  
**Fecha**: Junio 2026  
**Documento ejecutivo**: [`docs/index.html`](../docs/index.html)

Este documento es la referencia técnica de implementación. La narrativa de negocio, métricas visuales, flujos de escalamiento y visión futura se encuentran en `docs/index.html`.

---

## 0. Supuestos Declarados

| Supuesto | Impacto en diseño | Plan alternativo |
|---|---|---|
| Billing API accesible desde VPC vía REST/gRPC | El Agent Lambda llama directamente a la API | Integración batch vía S3 + Glue; saldo con latencia de 24h |
| CRM con escritura vía API REST o SDK | Registro automático de promesas en tiempo real | Cola SQS + worker batch que escribe vía SFTP/archivo |
| Meta Business API habilitada para número LLA | Canal WhatsApp operativo | Proceso no técnico — aprobación Meta puede tomar semanas |
| Historial de promesas incumplidas en CRM | Perfil de riesgo usa 3 señales desde el inicio | Primera campaña usa solo días de mora y monto; perfil aprende |
| Volumen de morosos simultáneos < 100,000 | SQS FIFO a 300 TPS es suficiente | Migrar a Kinesis Data Streams para >1M simultáneos |
| Consentimiento de contacto incluido en contrato | Permite contacto outbound sin opt-in adicional | Campaña de opt-in previa al lanzamiento |
| Latencia Bedrock (Claude 3.5 Haiku) < 3s | Margen para lograr p95 < 5s incluyendo tools | Circuit breaker con mensaje de "procesando" + respuesta asíncrona |
| Reglas de negocio cambian semanalmente, no en tiempo real | AppConfig con caché de 60s es adecuado | Reducir TTL a 5s si se requiere actualización más frecuente |

**Nota sobre bases de datos de LLA:** Este diseño no asume tecnología específica (PostgreSQL, Oracle, Cassandra, etc.) para los sistemas core de LLA. La integración es siempre vía API — la tecnología subyacente del sistema de facturación o CRM es irrelevante mientras la API sea accesible desde la VPC.

---

## 1. Arquitectura AWS

### 1.1 Componentes y justificación

#### Ingesta

**API Gateway HTTP API** (no REST API)  
WhatsApp exige HTTP 200 en <5 segundos o reintenta. HTTP API cubre este caso y cuesta 70% menos que REST API ($1.00 vs $3.50/millón requests). Las características avanzadas de REST API (caching, usage plans) no se necesitan para un webhook receiver.

**Amazon SQS FIFO**  
Desacopla recepción de procesamiento. El 200 va a Meta en milisegundos; el LLM toma 2–5 segundos. FIFO garantiza orden por cliente (`MessageGroupId = NumeroTelefono`), evitando race conditions cuando el cliente envía dos mensajes en sucesión rápida. Capacidad: 300 TPS.

**Sin Lambda Authorizer separado**  
La firma Meta (`x-hub-signature-256`) se valida dentro del Agent Lambda tras leer de SQS. Elimina un hop de red y un cold start adicional en el path crítico. Si la firma es inválida, el mensaje se descarta silenciosamente — Meta ya recibió su 200.

#### Procesamiento

**AWS Lambda — ¿Punto único de falla?**  
No. Lambda tiene alta disponibilidad nativa: múltiples zonas de disponibilidad, escalado horizontal a miles de instancias, SLA de 99.95%. Los riesgos reales son:
- **Bug en código** → mitigado con DLQ que captura fallos para análisis y reproceso
- **Timeout** → Circuit breaker envía mensaje de fallback al cliente antes de expirar
- **Cold start** → Provisioned Concurrency configurable durante horas de campaña

Cada invocación procesa exactamente un turno (no toda la sesión), manteniéndose dentro del límite de 15 minutos de Lambda.

**Sin Tool Lambdas intermedias**  
El Agent Lambda llama directamente a Billing y CRM APIs con IAM Least Privilege. Elimina 200–500ms de latencia y un cold start adicional por herramienta invocada. Solo aplica si las APIs son accesibles desde la VPC (ver supuesto).

#### Modelos de IA — Selección por tarea

| Agente | Tarea | Modelo | Razón técnica | Costo relativo |
|---|---|---|---|---|
| Validador | Clasificación binaria (sí/no/no soy titular) | Amazon Nova Micro | Tarea simple; LLM de gran tamaño es overkill | ~$0.035/M tokens |
| Negociador | Razonamiento multi-paso, detección de tono, persuasión, cálculo de fechas | Claude 3.5 Haiku | Mayor capacidad de razonamiento de la familia. Detecta hostilidad y evasión con contexto | ~$0.80/M tokens |
| Registrador | Extracción de entidades estructuradas (monto, fecha) de historial corto | Amazon Nova Lite | Supera a Micro en extracción con contexto; 5× más barato que Haiku | ~$0.06/M tokens |
| Cierre | Texto formulaico de confirmación | Amazon Nova Lite | No requiere creatividad; texto basado en plantilla | ~$0.06/M tokens |
| Supervisor | Filtrado de compliance | Bedrock Guardrails | No es LLM call — filtro nativo integrado en la invocación. 100× más barato | ~$0.15/1000 unidades |

**Modelos descartados:**
- GPT-4o Mini: capacidad similar a Haiku pero requiere salir de AWS (privacidad de datos, latencia de red, vendor adicional)
- Claude 3.5 Sonnet para todos los agentes: 3× más caro que Haiku con mejora marginal para tareas de cobranza estructuradas
- Reglas deterministas sin LLM para el Validador: descartado porque el lenguaje natural de confirmación de identidad es demasiado variado

#### Estado y Memoria

**DynamoDB — Metadata de sesión**  
Estado de la sesión: teléfono, fase actual, timestamp, clave S3 del historial, perfil de riesgo calculado. TTL de 48h para auto-expirar sesiones cerradas. Partition key: `COUNTRY_ID#PHONE_NUMBER` para escalabilidad multi-país.

**S3 — Historial de conversaciones**  
DynamoDB tiene límite de 400KB/item. Una conversación de 35 turnos con tool calls puede superar ese límite. S3 no tiene límite, cuesta 3× menos por GB, y permite análisis con Athena. Lifecycle Policy: 90 días en S3 Standard (hot), luego S3 Glacier para auditoría regulatoria.

Key structure: `conversations/{COUNTRY}/{PHONE}/{DATE}.json`

#### Campaña Outbound

**Step Functions Express — ¿Por qué?**  
Las campañas outbound pueden tener 100,000 clientes. Step Functions Express orquesta el envío con rate limiting (respetar límites de Meta API), reintentos configurables y manejo de errores. Express Workflows cuestan $1.00/millón de transiciones — 40× más barato que Standard, diseñado para alta frecuencia y corta duración.

**EventBridge Scheduler — Follow-ups**  
Cuando el agente espera respuesta, programa un evento para X horas. Al dispararse, una Lambda verifica `LastInteractionTime` en DynamoDB. Si el cliente no respondió, reactiva el agente con historial completo e instrucción de re-acercamiento contextual. Costo: $1.00/millón invocaciones.

#### WAF — ¿Es necesario?

Sí. Un script malicioso enviando 10,000 mensajes genera ~$20 en Bedrock sin WAF. Con WAF: $0.01/millón de requests inspeccionados. ROI positivo ante el primer ataque. Configura rate limiting por IP y por número de teléfono (segunda capa en DynamoDB).

---

## 2. Selección de Modelos de Agentes

### Perfil de riesgo del cliente

El perfil se calcula al inicio de cada sesión con datos del Billing API y CRM ya disponibles — no requiere base de datos adicional ni proceso de batch:

```python
def calcular_perfil_riesgo(billing_data: dict, crm_data: dict) -> str:
    dias_mora = billing_data["dias_vencido"]
    monto = billing_data["saldo_vencido"]
    promesas_incumplidas = crm_data.get("promesas_incumplidas", 0)  # default 0 si no existe

    if dias_mora <= 15 and monto < 50 and promesas_incumplidas == 0:
        return "BAJO"
    elif dias_mora <= 60 and monto <= 200 and promesas_incumplidas <= 1:
        return "MEDIO"
    else:
        return "ALTO"
```

**Actualización dinámica durante la sesión:** El Negociador detecta señales en la respuesta del cliente (hostilidad, evasión, cooperación) y las registra en CRM al finalizar la sesión para enriquecer el perfil en futuras interacciones.

---

## 3. Flujo de Escalamiento

### Árbol de decisión del Negociador

```
Inicio de negociación
│
├── ① Ofrecer pago total
│   ├── Acepta → generar_link_pago() → Registrador → Cierre
│   └── Rechaza → continuar
│
├── ② Ofrecer plan 2 cuotas
│   ├── Acepta → registrar_promesa_pago() → Cierre
│   └── Rechaza → continuar
│
├── ③ Ofrecer plan 3 cuotas (si perfil MEDIO o ALTO)
│   ├── Acepta → registrar_promesa_pago() → Cierre
│   └── Rechaza → continuar
│
├── ④ Proponer promesa de pago con fecha libre
│   ├── Acepta fecha → registrar y agendar follow-up
│   └── Evade o no se compromete → continuar
│
├── ⑤ Ofrecer canal alternativo (portal web, sucursal)
│   ├── Acepta → cierre con follow-up
│   └── Continúa evadiendo → escalar
│
└── ⑥ escalar_a_humano(motivo="sin_acuerdo")
    └── Entrega historial completo al asesor
```

### Escalamientos inmediatos (sin árbol)

| Trigger | Acción | Actualiza perfil CRM |
|---|---|---|
| Lenguaje hostil o insultos | `escalar_a_humano(motivo="cliente_agresivo")` | Sí — flag `contacto_hostil: true` |
| "Quiero hablar con una persona / agente / ejecutivo" | `escalar_a_humano(motivo="solicitud_cliente")` | No |
| Dispute de deuda ("yo ya pagué") | `escalar_a_humano(motivo="disputa_facturacion")` | Sí — flag `disputa_pendiente: true` |
| Turno 30 sin acuerdo | Ofrecer proactivamente canal humano | No |
| Turno 35 (límite) sin acuerdo | `escalar_a_humano(motivo="limite_sesion")` | Sí — flag `sesion_agotada: true` |

**Sobre el límite de 35 turnos:** El límite por defecto es 35 (ajustado para el cliente latinoamericano que tiende a la evasión y el diálogo extenso). Es configurable en AppConfig sin redesplegar código. En el turno 30, el agente ofrece proactivamente el canal humano. Si el cliente prefiere continuar y hay progreso activo en la conversación, un operador puede extender el límite desde AppConfig en tiempo real.

### Gestión de opt-out en español

El sistema reconoce variantes en español además del estándar inglés "STOP":

**Opt-out permanente** (no contactar en ninguna campaña futura del mismo canal):
- STOP, ALTO, DETENER, PARA, NO ME CONTACTES, NO QUIERO QUE ME CONTACTEN, BASTA

**No interesado ahora** (programar follow-up):
- NO AHORA, DESPUÉS, MÁS TARDE, MAÑANA, LLAMAME DESPUÉS, EN OTRO MOMENTO

**Solicitud de humano**:
- AGENTE, PERSONA, EJECUTIVO, HABLAR CON ALGUIEN, QUIERO UN HUMANO, ASESOR

La detección es case-insensitive y tolera variantes con/sin acento.

---

## 4. IAM Least Privilege

```
Agent Lambda Role:
  ✓ bedrock:InvokeModel (modelos específicos en us-east-1)
  ✓ bedrock:ApplyGuardrail (guardrail ID específico)
  ✓ dynamodb:GetItem / PutItem (tabla sesiones únicamente)
  ✓ s3:GetObject / s3:PutObject (bucket chats únicamente)
  ✓ secretsmanager:GetSecretValue (secrets específicos por ARN)
  ✗ dynamodb:Scan / DeleteItem / Query sin condición
  ✗ s3:DeleteObject / s3:ListBucket completo
  ✗ bedrock:* (wildcard — no permitido)

Step Functions Role:
  ✓ s3:GetObject (bucket campañas)
  ✓ sqs:SendMessage (cola ingesta)
  ✗ bedrock:* (no invoca modelos)
  ✗ crm:* (no escribe CRM)
```

---

## 5. Observabilidad

**CloudWatch + X-Ray:** Tracing distribuido de Lambda → Bedrock → APIs externas. Dashboard con métricas custom.

**Datadog (opcional):** Para equipos con Datadog existente, la extensión Lambda permite emitir métricas sin modificar permisos IAM (vía CloudWatch Logs).

**Dead Letter Queue (DLQ):** Mensajes que fallan 3 veces llegan a DLQ. Una alarma CloudWatch se activa ante cualquier mensaje en DLQ — señal de bug crítico en el código.

**Métricas técnicas clave:**

| Métrica | Meta | Alarma si |
|---|---|---|
| `lla.agent.response.latency` p95 | < 5,000ms | > 6,000ms |
| `lla.agent.response.latency` p99 | < 8,000ms | > 10,000ms |
| `lla.agent.error.rate` | < 0.5% | > 1% |
| `lla.agent.guardrail.blocked` | < 2% | > 5% en ventana 5min |
| `lla.security.input.rejected` | baseline | spike > 2× baseline |
| DLQ message count | 0 | > 0 en 5min |

---

## 6. Estimación de Costos

### 10,000 conversaciones / mes

| Servicio | Costo/mes |
|---|---|
| API Gateway HTTP API | $0.05 |
| SQS FIFO | $0.03 |
| Lambda (orquestador) | $0.80 |
| Bedrock Nova Micro (Validador) | $0.60 |
| Bedrock Claude 3.5 Haiku (Negociador) | $4.00 |
| Bedrock Nova Lite (Registrador + Cierre) | $1.00 |
| Bedrock Guardrails | $3.75 |
| DynamoDB on-demand | $0.50 |
| S3 (historial + campañas) | $0.30 |
| EventBridge + Step Functions | $0.01 |
| Secrets Manager | $2.00 |
| WAF + CloudWatch + X-Ray | $8.05 |
| **TOTAL infraestructura** | **~$21/mes** |

### Costo real ponderado (incluyendo escalamiento humano)

Con 20% de escalamiento a asesor humano ($3.50/llamada):

| Canal | Volumen | Costo unitario | Total |
|---|---|---|---|
| Agente IA (80%) | 8,000 | $0.002 | $16 |
| Asesor humano (20%) | 2,000 | $3.50 | $7,000 |
| **Costo total mixto** | 10,000 | | **~$7,016/mes** |
| Sin IA (baseline) | 10,000 | $3.50 | $35,000/mes |
| **Ahorro real** | | | **~80%** |

La comparación directa $0.002 vs $2-5 es válida solo para el 80% de conversaciones resueltas por IA. El número honesto es 80% de reducción de costo total, no 99.9%.

### 100,000 conversaciones / mes

| Componente | Costo/mes |
|---|---|
| Servicios de cómputo y mensajería | ~$85 |
| Bedrock (todos los modelos + Guardrails) | ~$95 |
| Almacenamiento y configuración | ~$15 |
| Observabilidad | ~$10 |
| **TOTAL infraestructura** | **~$205/mes** |

Costo ponderado real (80/20 split): ~$70,000/mes vs $350,000 sin IA — 80% de ahorro.

### Optimizaciones de costo

1. **Bedrock Prompt Caching:** System prompts idénticos entre usuarios → 90% menos en tokens de entrada. Mayor impacto por costo.
2. **Truncar historial:** Últimos 10 turnos en lugar del historial completo → reducción lineal en tokens.
3. **Reducir tasa de escalamiento:** Pasar del 20% al 15% tiene mayor impacto económico que cualquier optimización de infraestructura ($3.50 × 500 conversaciones = $1,750/mes).
4. **Provisioned Concurrency Lambda:** Solo durante horas de campaña — reduce cold starts sin pagar 24/7.

---

## 7. Visión Futura — Plataforma CX Multi-Agente

Este sistema es el Módulo 1 de una plataforma de Customer Experience completa. La arquitectura de la plataforma completa y la hoja de ruta se describen en `docs/index.html` → sección "Visión Futura".

El componente clave es un **CX Resolver** que recibe todos los mensajes entrantes del cliente y clasifica la intención para enrutar al agente especializado correcto (Cobranza, Ventas, Soporte Técnico, Operaciones). Todos los módulos comparten una capa de perfil unificado del cliente y Guardrails.
