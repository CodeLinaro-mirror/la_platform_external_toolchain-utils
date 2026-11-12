- AMDGPU-specific: Paths with `/Target/AMDGPU/` or `/amdgpu/`, or generic
  files where changes only affect AMDGPU (e.g., guarded by AMDGPU checks or
  AMDGPU intrinsics). Target-specific subdirectories within non-exempt top-level
  directories (e.g., `libc/.../amdgpu/`) are fully exempt.
- Flang-specific: Paths with `flang/`, or generic files where changes only
  affect Flang.
- CUDA/NVPTX-specific: Paths with `/Target/NVPTX/`, `/NVPTX/`, or paths related
  to CUDA offload or CUDA support (e.g., CUDA runtime, headers, or
  CUDA-specific codegen). Target-specific subdirectories within non-exempt
  top-level directories (e.g., `libc/.../cuda/` or `libc/.../nvptx/`) are fully
  exempt.
- LoongArch-specific: Paths with `/Target/LoongArch/` or `/LoongArch/`, or
  generic files where changes only affect LoongArch.
- libclc-specific: Paths with `libclc/`, or generic files where changes only
  affect libclc.
- COFF/DirectX/HLSL-specific: Paths with `/Target/DirectX/`, `/DirectX/`,
  `/HLSL/`, `HLSL`, or COFF/DirectX/HLSL-specific files, or generic files where
  changes only affect COFF, DirectX, or HLSL.
- MLIR-specific: Paths with `mlir/`, or other files (such as build or test
  tooling configs) where changes only affect or are made to support MLIR.
- MIPS-specific: Paths with `/Target/Mips/` or `/Mips/`, or generic files where
  changes only affect MIPS.
- Incidental supporting changes for another exempt category: Small supporting
  edits in shared headers, driver/frontend plumbing, build configs, helpers, or
  tests (e.g., target-specific enums, diagnostics, options, or constraint codes;
  pass-through virtual hooks with default implementations; minor assertion
  tweaks; or refactoring/reverting shared helpers or tests only meaningfully
  used by that exempt category) that do not meaningfully change behavior for
  non-exempt targets, unlike substantive changes to shared passes/analyses or
  non-exempt targets' non-test code.
