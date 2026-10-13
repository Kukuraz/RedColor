; RedColor — установщик (Inno Setup 6). Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
; Бланки и цитаты в установщик не входят: пользователь выбирает папку бланков и заполняет цитаты сам.

#ifndef DistDir
  #define DistDir "..\dist\RedColor"
#endif
#ifndef RootDir
  #define RootDir ".."
#endif
#define AppName "RedColor"
#define AppVer "1.1"
#define Author "Maksim Belonoskin"
#define AuthorFull "Maksim Belonoskin, Zelenograd, Moscow, Russia"

[Setup]
AppId={{6E2B7F0A-4C1D-4B7E-9C3A-5D1F0E7A9B21}
AppName={#AppName}
AppVersion={#AppVer}
AppVerName={#AppName} {#AppVer}
AppPublisher={#AuthorFull}
AppCopyright=© 2026 {#AuthorFull}
AppComments=Редактор PDF для проверки работ. Автор: {#AuthorFull}
VersionInfoCompany={#Author}
VersionInfoCopyright=© 2026 {#AuthorFull}
VersionInfoDescription=Установка RedColor — редактора PDF для проверки работ
VersionInfoProductName={#AppName}
VersionInfoVersion=1.1.0.0
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=RedColor_Setup_{#AppVer}
SetupIconFile={#RootDir}\assets\redcolor.ico
UninstallDisplayIcon={app}\RedColor.exe
UninstallDisplayName={#AppName} {#AppVer}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ChangesAssociations=yes
ShowLanguageDialog=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Messages]
russian.WelcomeLabel2=Будет установлен [name/ver] — редактор PDF для проверки работ.%n%nАвтор: {#AuthorFull}.%n%nБланки и цитаты в комплект не входят: после установки выберите свою папку с бланками и добавьте цитаты (Меню → «Цитаты…»).

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Ярлыки:"
Name: "pdfassoc"; Description: "Зарегистрировать RedColor как программу для открытия PDF"; GroupDescription: "PDF:"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RootDir}\assets\info.html"; DestDir: "{app}"; DestName: "Информация RedColor.html"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\RedColor.exe"; Comment: "Редактор PDF для проверки работ. {#AuthorFull}"
Name: "{autoprograms}\{#AppName} — информация"; Filename: "{app}\Информация RedColor.html"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\RedColor.exe"; Tasks: desktopicon; Comment: "Редактор PDF для проверки работ. {#AuthorFull}"

[Registry]
Root: HKCU; Subkey: "Software\Classes\RedColor.PDF"; ValueType: string; ValueName: ""; ValueData: "Документ PDF (RedColor)"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\RedColor.PDF"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "Документ PDF"; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\RedColor.PDF\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\RedColor.exe,0"; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\RedColor.PDF\Application"; ValueType: string; ValueName: "ApplicationName"; ValueData: "RedColor"; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\RedColor.PDF\Application"; ValueType: string; ValueName: "ApplicationCompany"; ValueData: "{#AuthorFull}"; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\RedColor.PDF\Application"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Редактор PDF для проверки работ"; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\RedColor.PDF\shell\open"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "RedColor"; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\RedColor.PDF\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\RedColor.exe"" ""%1"""; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "RedColor.PDF"; ValueData: ""; Flags: uninsdeletevalue; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\Applications\RedColor.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "RedColor"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\Applications\RedColor.exe\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\Applications\RedColor.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\RedColor.exe"" ""%1"""; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\RedColor\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "RedColor"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\RedColor\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Редактор PDF для проверки работ. {#AuthorFull}"; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\RedColor\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: "{app}\RedColor.exe,0"; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\RedColor\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "RedColor.PDF"; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "RedColor"; ValueData: "Software\RedColor\Capabilities"; Flags: uninsdeletevalue; Tasks: pdfassoc

[Run]
Filename: "{app}\RedColor.exe"; Description: "Запустить RedColor"; Flags: nowait postinstall skipifsilent
Filename: "ms-settings:defaultapps?registeredAppUser=RedColor"; Description: "Открыть настройки Windows, чтобы выбрать RedColor программой для PDF по умолчанию"; Flags: shellexec postinstall skipifsilent unchecked; Tasks: pdfassoc
