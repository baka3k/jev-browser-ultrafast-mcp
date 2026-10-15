# Quick Start: Jev MCP Server cho IDE

## Cài đặt (1 lần)

```bash
cd jev-ultrafast
make build             # uv sync + toàn bộ checks (hoặc tự chạy: uv sync)
make install cursor    # tự đăng ký MCP cho Cursor — agent khác: claude codex commandcode
                       # vscode qwen ayg gemini opencode zcode, hoặc all
make doctor            # kiểm tra tình trạng toàn bộ: deps, keys, Chrome, MCP
```

## Cấu hình Cursor

1. Mở **Cursor Settings** (Cmd+,)
2. Vào **MCP** tab
3. Click **Add Server**
4. Điền:
   - **Name**: `jev-browser`
   - **Command**: `uv`
   - **Args**: `run,jev-mcp`
   - **Working Directory**: `/Users/absolute/path/to/test/jev-ultrafast`

Hoặc paste JSON:

```json
{
  "name": "jev-browser",
  "command": "uv",
  "args": ["run", "jev-mcp"],
  "cwd": "/Users/absolute/path/to/test/jev-ultrafast"
}
```

## Cấu hình VSCode Copilot

1. Mở **Settings** (Cmd+,)
2. Search: `copilot mcp`
3. Click **Edit in mcp.json**
4. Thêm:

```json
{
  "servers": {
    "jev-browser": {
      "command": "uv",
      "args": ["run", "jev-mcp"],
      "cwd": "${workspaceFolder}"
    }
  }
}
```

## Sử dụng

### Trong Cursor/Copilot Chat

```
Bạn: Mở Google và search "Python tutorial"
```

IDE sẽ tự động:
1. Gọi `jev_navigate("https://www.google.com")`
2. Gọi `jev_observe()` để xem elements
3. Gọi `jev_act(action_id, text)` để điền và search
4. Report kết quả

### Ví dụ khác

```
Bạn: Vào Wikipedia tìm bài về "Machine learning"

Bạn: Mở form đăng ký và điền:
     - Name: John Doe
     - Email: john@example.com

Bạn: Kiểm tra giá vé máy bay từ Hà Nội đi Tokyo ngày 15/12
```

## Tools có sẵn

- `jev_navigate(url)` - Mở URL
- `jev_observe()` - Đọc page state + elements
- `jev_act(action_id, text?)` - Click/type/select
- `jev_close()` - Đóng browser

## Kiểm tra hoạt động

Trong Cursor chat:

```
Bạn: List available MCP tools
```

Nếu thấy `jev_navigate`, `jev_observe`, etc. → OK ✅

## Troubleshooting

### Server không kết nối

```bash
# Test manual
cd jev-ultrafast
uv run jev-mcp
# Nếu chạy được → server OK, vấn đề là config
```

### Chrome hỏi permission

```bash
uv run browser-harness mac-approve
# Hoặc click "Allow" trong Chrome
```

### Action không tìm thấy

```
# Observe lại để lấy action_ids mới
Bạn: Observe lại page
```

## So sánh nhanh

| | TypeSafe Agent | IDE Agent (MCP) |
|---|---|---|
| **License** | Cần API key | Dùng license có sẵn |
| **Tốc độ** | ~200ms | ~1-5s |
| **Cost** | ~$0.001/action | Included |
| **Intelligence** | Specialized | General purpose |
| **Use case** | Production, repeated tasks | Ad-hoc, complex reasoning |

## Tips

✅ **Be specific**: "Tìm chuyến bay từ A đến B ngày X" thay vì "đặt vé"
✅ **Break down tasks**: Chia nhỏ task phức tạp
✅ **Verify**: Luôn hỏi IDE confirm kết quả
✅ **Screenshots**: Dùng khi cần visual confirmation

## Next steps

- Xem `examples/` cho các use cases
- Tạo custom prompts trong `.cursorrules`
