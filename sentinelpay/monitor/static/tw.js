// Tailwind theme from the SentinelPay Stitch design (DESIGN.md). Loaded right after the Tailwind CDN script.
tailwind.config = {
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        "surface-container-low": "#131b2e", "secondary-container": "#04b4a2", "primary": "#4cd7f6",
        "primary-container": "#06b6d4", "surface-tint": "#4cd7f6", "on-tertiary": "#00354a",
        "inverse-surface": "#dae2fd", "surface-bright": "#31394d", "primary-fixed": "#acedff",
        "on-secondary-container": "#003f38", "inverse-primary": "#00687a", "on-primary-fixed": "#001f26",
        "secondary-fixed": "#71f8e4", "background": "#0b1326", "on-secondary": "#003731",
        "primary-fixed-dim": "#4cd7f6", "on-surface": "#dae2fd", "tertiary-fixed": "#c4e7ff",
        "on-primary": "#003640", "surface-dim": "#0b1326", "surface-container": "#171f33",
        "outline": "#869397", "surface-container-high": "#222a3d", "secondary": "#4fdbc8",
        "tertiary": "#7bd0ff", "surface-variant": "#2d3449", "on-primary-container": "#00424f",
        "surface-container-lowest": "#060e20", "surface-container-highest": "#2d3449",
        "surface": "#0b1326", "on-surface-variant": "#bcc9cd", "tertiary-container": "#23b2ec",
        "on-error": "#690005", "outline-variant": "#3d494c", "on-error-container": "#ffdad6",
        "error-container": "#93000a", "error": "#ffb4ab", "warn": "#F5B841", "ok": "#4CC38A"
      },
      borderRadius: { "DEFAULT": "0.125rem", "lg": "0.25rem", "xl": "0.5rem", "full": "9999px" },
      spacing: { "gutter": "1rem", "space-md": "0.75rem", "space-lg": "1rem", "margin": "1.5rem",
                 "space-sm": "0.5rem", "space-xs": "0.25rem", "space-xl": "1.5rem" },
      fontFamily: {
        "headline-xl": ["Inter"], "headline-lg": ["Inter"], "headline-md": ["Inter"], "headline-sm": ["Inter"],
        "body-sm": ["Inter"], "body-md": ["Inter"], "body-lg": ["Inter"],
        "label-sm": ["JetBrains Mono"], "label-md": ["JetBrains Mono"], "label-lg": ["JetBrains Mono"],
        "metric-sub": ["JetBrains Mono"], "metric-display": ["JetBrains Mono"], "mono": ["JetBrains Mono", "monospace"]
      },
      fontSize: {
        "headline-xl": ["2rem", { lineHeight: "2.5rem", letterSpacing: "-0.025em", fontWeight: "600" }],
        "headline-lg": ["1.5rem", { lineHeight: "2rem", letterSpacing: "-0.02em", fontWeight: "600" }],
        "headline-md": ["1.25rem", { lineHeight: "1.75rem", letterSpacing: "-0.015em", fontWeight: "600" }],
        "headline-sm": ["1.125rem", { lineHeight: "1.5rem", letterSpacing: "-0.01em", fontWeight: "500" }],
        "label-lg": ["0.875rem", { lineHeight: "1.25rem", letterSpacing: "-0.01em", fontWeight: "500" }],
        "label-md": ["0.75rem", { lineHeight: "1rem", letterSpacing: "0em", fontWeight: "500" }],
        "label-sm": ["0.6875rem", { lineHeight: "0.875rem", letterSpacing: "0.02em", fontWeight: "400" }],
        "body-lg": ["1rem", { lineHeight: "1.5rem", letterSpacing: "0em", fontWeight: "400" }],
        "body-md": ["0.875rem", { lineHeight: "1.25rem", letterSpacing: "0em", fontWeight: "400" }],
        "body-sm": ["0.75rem", { lineHeight: "1rem", letterSpacing: "0.01em", fontWeight: "400" }],
        "metric-sub": ["1.125rem", { lineHeight: "1.375rem", letterSpacing: "-0.02em", fontWeight: "500" }],
        "metric-display": ["1.75rem", { lineHeight: "2rem", letterSpacing: "-0.03em", fontWeight: "600" }]
      }
    }
  }
};
