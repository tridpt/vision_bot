Set WshShell = CreateObject("WScript.Shell")
' Số 0 ở cuối lệnh có nghĩa là "Hide" (Ẩn cửa sổ Terminal hoàn toàn)
WshShell.Run "pythonw.exe D:\App\vision_bot\bot_giam_sat.py", 0, False
Set WshShell = Nothing
