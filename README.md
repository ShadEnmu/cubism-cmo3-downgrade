# Cubism .cmo3 downgrade: 5.4 alpha → 5.3

**[Русский](#русский) | [English](#english)**

> ⚠️ **Unofficial tool.** Not affiliated with, endorsed by, or supported by Live2D Inc. "Live2D" and "Cubism" are trademarks of Live2D Inc.
> Always keep a backup of your original model.

---

## Русский

Конвертирует модели `.cmo3`, сохранённые в **Live2D Cubism Editor 5.4 alpha**, в формат **5.3**, чтобы их можно было открыть и продолжить работу в 5.3 после окончания срока alpha-версии.

При открытии такого файла в 5.3 появляется ошибка:

```
[ERROR] Class not found: LayerMergeSet
[ERROR] Serializer not found: LayerMergeSet
...
java.lang.NullPointerException at com.live2d.serialize.XmlReader.readRootObject
```

### Как пользоваться

1. Скачайте архив из раздела [Releases](../../releases) и распакуйте его.
2. Запустите `Cmo3_54_to_53.exe`.
3. Нажмите **«Выбрать…»** и укажите модель из 5.4 alpha.
4. Нажмите **«Конвертировать»**. Результат сохранится рядом с исходным файлом с припиской `_5.3`.
5. Откройте результат в Cubism 5.3 и **сохраните его там**. После этого файл станет «родным» для 5.3.

Исходный файл не изменяется.

### Что делает конвертер

| Функция 5.4 | Что происходит |
|---|---|
| Сжатые слои PSD (`CPsdCompressedImage`) | Распаковываются в PNG, как хранит 5.3 |
| Наборы объединения слоёв (`LayerMergeSet`) и фильтр `CLayerMergeSetFilter` | Каждая текстура переподключается напрямую к своему слою (фильтры `CLayerSelector` + `CLayerFilter` из 5.3) |
| Model State Set | Удаляется |
| Пустые маски слоёв | Удаляются |
| Версия формата | Понижается до 5.3 |

### Ограничения

Конвертер останавливается с понятной ошибкой и ничего не записывает, если в модели есть то, что нельзя перенести без потерь:

- текстура объединяет **несколько слоёв** в одном наборе;
- внутри набора объединения слой скрыт, имеет прозрачность или маску;
- используются **маски слоёв**.

Если Model State Set не пустой, он будет удалён, и программа предупредит об этом.

Проверено на моделях из Cubism Editor 5.4 alpha1 и 5.3. Формат `.cmo3` официально не документирован, поэтому **всегда делайте резервную копию** и проверяйте результат в редакторе.

### Предупреждения антивирусов

Сборка сделана через PyInstaller и не подписана, поэтому некоторые антивирусы могут показать ложное срабатывание: `Wacatac!ml`, «Static ML», «Suspicious PE» и т. п. Программа не обращается к сети и читает и записывает только выбранные вами файлы. Если сомневаетесь, запустите её из исходников (см. ниже) или соберите сами.

### Запуск из исходников

Нужен Python 3.9+ (с tkinter, он входит в стандартный установщик для Windows). Сторонние библиотеки не нужны.

```bash
python src/gui.py
```

Командная строка:

```bash
python src/cmo3conv.py model_5.4.cmo3 model_5.3.cmo3
```

### Сборка .exe

```bash
build.bat
```

Результат появится в `dist/Cmo3_54_to_53/`. Также релизы собираются автоматически через GitHub Actions при публикации тега `v*`.

---

## English

Converts `.cmo3` models saved in **Live2D Cubism Editor 5.4 alpha** to the **5.3** format, so they can be opened in 5.3 after the alpha has expired.

Opening such a file in 5.3 fails with `Class not found: LayerMergeSet` followed by a `NullPointerException` in `XmlReader.readRootObject`.

### Usage

1. Download the archive from [Releases](../../releases) and extract it.
2. Run `Cmo3_54_to_53.exe`.
3. Click **«Выбрать…»** (Browse) and pick your 5.4 alpha model.
4. Click **«Конвертировать»** (Convert). The result is saved next to the original with a `_5.3` suffix.
5. Open it in Cubism 5.3 and **save it there**.

The original file is never modified.

### What it does

- Decompresses 5.4 PSD layer storage (`CPsdCompressedImage`) into PNG layer images as used by 5.3.
- Replaces `LayerMergeSet`-based texture inputs with 5.3's `CLayerSelector` + `CLayerFilter` filter chain pointing at the same layer.
- Removes the Model State Set, empty layer masks and other 5.4-only fields, and sets the file format version to 5.3.

### Limitations

The converter refuses (and writes nothing) when a model uses features that cannot be represented in 5.3 without loss: merge sets with multiple layers, hidden/semi-transparent/masked layers inside a merge set, or layer masks. A non-empty Model State Set is dropped with a warning.

The `.cmo3` format is undocumented. **Keep backups** and check the result in the editor.

### Antivirus warnings

The executable is built with PyInstaller and is unsigned, which triggers heuristic false positives on some engines. The tool has no network access and only touches the files you select. You can run it from source or build it yourself.

### From source

Python 3.9+ with tkinter, no third-party packages:

```bash
python src/gui.py
python src/cmo3conv.py input_5.4.cmo3 output_5.3.cmo3
```

Build: `build.bat` → `dist/Cmo3_54_to_53/`. Tagged pushes (`v*`) are built by GitHub Actions.

## License

[MIT](LICENSE)
