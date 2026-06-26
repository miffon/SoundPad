# SoundPad

SoundPad 是一個音效板 GUI
1. 每頁有 16 個 pad, 可以新增無限多頁
2. drag-and-drop 放入 WAV 或 MP3
3. 右鍵 pad 調整 trim range, fade in/out 與 gain
4. 在 waveform 上滾輪縮放, 中鍵 (或 space + 左鍵) 拖動, 右鍵快速 preview
5. 選擇音訊輸出裝置
6. 按鍵播放
7. 可用 Kill 中斷播放
8. Edit Panel 拖放來排版

## 系統需求

* Python 3.14
* uv
* Windows / macOS / Linux
* ffmpeg (for MP3)

如果 MP3 無法正常讀取, 請確認系統中已安裝並可使用 `ffmpeg`

## 安裝

clone 專案後, 在專案目錄中執行:

```sh
uv sync
```


## 啟動方式

Windows：

```bat
soundpad.bat
```

macOS：

```sh
./soundpad.command
```

Linux / WSL：

```sh
./soundpad.sh
```

如果在 macOS 或 Linux 執行時出現權限不足, 請先執行：

```sh
chmod +x soundpad.command soundpad.sh
```

## 免安裝版

可以到 GitHub Releases 下載免安裝可執行檔

Windows 版下載 `SoundPad-Windows.zip`, 解壓後會是:

```text
SoundPad/
  SoundPad.exe
  soundpad/
    theme.toml
    assets/
```

執行 `SoundPad.exe` 即可啟動, 程式會在同一個資料夾建立本機資料:

```text
SoundPad/
  cache/
  soundpad/config.toml
```

macOS 版下載 `SoundPad-macOS.zip`, 解壓後開啟 `SoundPad.app` (未簽章版本第一次啟動可能需要右鍵 Open) 

macOS 版的設定文件與 cache 會放在:

```text
~/Library/Application Support/SoundPad/
```