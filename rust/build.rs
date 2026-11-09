fn main() {
    slint_build::compile("ui/app.slint").expect("slint");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        let out = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap()).join("bluecolor.res");
        let status = std::process::Command::new("rc.exe")
            .arg("/nologo").arg(format!("/fo{}", out.display())).arg("bluecolor.rc")
            .status().expect("Windows resource compiler rc.exe is required");
        assert!(status.success(), "failed to compile the BlueColor icon");
        println!("cargo:rustc-link-arg={}", out.display());
        println!("cargo:rerun-if-changed=bluecolor.rc");
        println!("cargo:rerun-if-changed=bluecolor.ico");
    }
}
