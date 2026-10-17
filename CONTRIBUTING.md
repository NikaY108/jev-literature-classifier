# 参与贡献

感谢你对 Jev 文献分类工作台感兴趣。提交问题或改动前，请先阅读
[AGENTS.md](AGENTS.md) 中的产品边界和数据安全要求。

## 开发环境

```powershell
conda create -n paper_manage python=3.12
conda activate paper_manage
pip install -r requirements.txt
python start_server.py
```

访问 <http://127.0.0.1:8000>。前端没有独立构建步骤。

## 提交改动

1. 让一次提交只解决一个明确问题。
2. 优先复用现有 FastAPI、原生 JavaScript 和 CSS 模式，避免无必要依赖。
3. 用户可见流程变化时，同步更新 `user-guide.md` 和 `TODO.md`。
4. 不要提交 `.env`、`data/`、PDF、数据库、API Key 或 Zotero 授权信息。
5. 涉及外部模型时使用模拟响应完成工程检查，不在测试中调用真实付费 API。

可使用以下命令进行本地检查：

```powershell
python -m ruff check .
python -m pytest
node --check frontend/app.js
```

## 问题报告

请说明操作步骤、预期结果、实际结果和运行环境。日志或截图必须先移除 API Key、
本地路径、私人文献元数据以及未授权论文内容。
