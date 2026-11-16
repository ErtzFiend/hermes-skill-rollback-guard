# assets/

`assets/banner.png` is **reserved** for the plugin's README/release banner.

It is intentionally absent from this repository: the artwork is produced separately and dropped in
at this exact path. No placeholder or synthetic image is committed — a real banner is added only
when the generated asset exists. Reference it from `README.md` once present:

```markdown
![hermes-skill-rollback-guard](assets/banner.png)
```
