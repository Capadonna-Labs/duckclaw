# Skills Olist BI

Cada archivo `.md` define un **skill**: conjunto de herramientas y cuándo usarlas según el requerimiento del usuario.

Formato Anthropic: frontmatter YAML (`name`, `description`, `allowed-tools`) + instrucciones en markdown.

El router carga estos skills como contexto para el modelo cuando la consulta es compuesta o ambigua.
