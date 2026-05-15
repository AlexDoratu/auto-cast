# Auto-Cast Flutter GUI

This is the Flutter desktop front end for Auto-Cast. It talks to the existing Python casting backend through `gui_bridge.py` using line-delimited JSON over stdin/stdout.

## Run

Install Flutter with Windows desktop support, then run from this folder:

```powershell
flutter pub get
flutter run -d windows
```

The Flutter app expects to be launched from the repository root or from `flutter_gui`; it locates `gui_bridge.py` in the parent directory when needed.
