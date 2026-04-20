# tv-sign-proxy boundary

role: edge ingress only

allowed:
- signature verification
- path normalization
- basic rate limiting
- origin shielding
- pass-through request logging
- header normalization
- upstream forwarding

forbidden:
- trade decision logic
- strategy logic
- approval / recovery state mutation
- runtime spine business-state mutation
- position / order execution logic
- DB truth ownership
- operator UI state ownership

rule:
- proxy is stateless where possible
- backend remains source of truth
- failures must fail closed for invalid signature
- valid requests should be forwarded unchanged except normalized headers/path
