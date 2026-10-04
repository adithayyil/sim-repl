{
  description = "Mutation audits of sensor-driver checks under Simantic/Renode";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      python = pkgs.python314;

      # The Simantic engine ships glibc-linked .so files (coreclr, libstdc++).
      # NixOS keeps neither on the library path, and dlopen has to find both.
      engineLibs = "${pkgs.gcc-unwrapped.lib}/lib:${pkgs.icu}/lib";
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        packages = [ python pkgs.uv pkgs.gcc-arm-embedded pkgs.ruff pkgs.git ];

        # uv must not download its own interpreter: NixOS has no ld-linux for it.
        UV_PYTHON = "${python}/bin/python";
        UV_PYTHON_DOWNLOADS = "never";

        shellHook = ''
          export LD_LIBRARY_PATH="${engineLibs}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
          echo "simplay dev shell"
          echo "  python: $(${python}/bin/python --version 2>&1)   arm gcc: $(arm-none-eabi-gcc -dumpversion)"
          echo "  uv sync && uv run simplay bme280 play"
        '';
      };
    };
}