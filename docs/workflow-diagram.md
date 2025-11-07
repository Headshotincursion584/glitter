## Glitter CI/CD 流程图

```
       +--------------------+
       | Push/PR to main?   |
       +---------+----------+
                 |
                 v
        +-------------------------+
        | any *.py files changed? |
        +---------+---------------+
                  |
        yes       | no
                  v
        +--------------------+             +-----------------+
        | pytest (ubuntu)    |             | skip pytest job |
        +--------------------+             +-----------------+
                 |
                 v
        +--------------------+
        | pytest (windows)   |
        +---------+----------+
                 |
                 v
   +-------------+--------------+
   | push to main & tests pass? |
   +-------------+--------------+
                 |
                 v
      +-------------------------+
      | prepare_release (检测)  |
      +----+---------------+----+
           |               |
           |release_changed?    pypi_changed?
           |               |
     yes   |               | yes
           v               v
+------------------+   +------------------+
| build_release    |   | publish_pypi     |
| (win + linux)    |   | (build + upload) |
+--------+---------+   +------------------+
         |
         v
  +------+-----------------------+
  | publish_release (gh-release) |
  +------------------------------+
```

> `pytest` 仅在 diff 中包含 `.py` 文件时才会运行；纯文档 / 资源改动会跳过。
> `prepare_release` 同时检查版本号文件 `glitter/__init__.py` 以及可执行/打包
> 相关文件（`glitter.spec`、`pyproject.toml`），以决定是否进行构建、发布或
> PyPI 推送。
