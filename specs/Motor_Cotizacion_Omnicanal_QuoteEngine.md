# Especificación Técnica: Motor de Cotización Omnicanal (Agnóstico al Canal)

## 1. Objetivo Arquitectónico

Desarrollar un motor de cotizaciones (QuoteEngine) que calcule precios, aplique reglas de negocio (descuentos, impuestos) y genere un documento formal (PDF/JSON). La entrega del documento se delega completamente al Orquestador de Eventos (n8n) mediante un webhook estandarizado, permitiendo que el cliente (Power Seal) decida visualmente en n8n por qué canal enviar la cotización (Email, WhatsApp, CRM externo) sin modificar el código del agente.

## 2. Topología de Desacoplamiento (Agent → n8n)

```mermaid
graph LR
    A[Agente: Genera Cotización] --> B[QuoteEngine: Calcula Totales]
    B --> C[DocumentGenerator: Crea PDF/JSON]
    C --> D[n8n Bridge: Dispara Webhook quote_ready]
    
    subgraph n8n (VPS)
        D --> E{Router de Canal}
        E -->|Preferencia: Email| F[Nodo: Send Email]
        E -->|Preferencia: WPP| G[Nodo: WhatsApp API]
        E -->|Backup| H[Nodo: Google Drive / SharePoint]
    end
```

## 3. QuoteEngine (Core Matemático)

**Entrada:** items (Lista de SKUs y cantidades), user_id (Teléfono o Email del lead).

**Lógica:** Validación en catalog_items/products, descuentos (>100 unidades), IVA 19% Colombia, persistencia en tabla quotes.

**Salida:** QuoteData (JSON estructurado).

## 4. DocumentDispatcher (Puente Omnicanal)

**Entrada:** QuoteData, delivery_preferences (opcional).

**Lógica:** Generar PDF en /tmp/quotes/, empaquetar payload para n8n, invocar N8N_QUOTE_WEBHOOK_URL.

**Salida:** "Cotización COT-2026-001 generada y enviada al sistema de distribución."

## 5. API Gateway: Descarga Segura

- **GET /api/v1/quotes/download/{quote_id}**: Token de un solo uso o autenticación. FileResponse (application/pdf).
- **Auditoría:** Registrar cuándo y desde qué IP se descargó.
