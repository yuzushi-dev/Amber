# Page snapshot

```yaml
- generic [ref=e2]:
  - banner [ref=e3]:
    - generic [ref=e4]:
      - img [ref=e6]
      - generic [ref=e9]:
        - heading "Welcome to Amber" [level=2] [ref=e10]
        - paragraph [ref=e11]: Enter your API key to get started
  - generic [ref=e12]:
    - generic [ref=e13]:
      - text: API Key
      - generic [ref=e14]:
        - textbox "API Key" [active] [ref=e15]:
          - /placeholder: Enter your API key...
        - button [ref=e16] [cursor=pointer]:
          - img [ref=e17]
    - button "Connect" [disabled] [ref=e21]
    - paragraph [ref=e22]: Your API key is stored locally and never sent to external servers.
```