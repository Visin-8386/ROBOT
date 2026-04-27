import ctypes
import os
import site
import glob
import onnxruntime as ort


def add_candidate_dirs() -> None:
    bases = []
    try:
        bases.append(site.getusersitepackages())
    except Exception:
        pass
    try:
        bases.extend(site.getsitepackages())
    except Exception:
        pass

    seen = set()
    for b in bases:
        for rel in [
            os.path.join("nvidia", "cudnn", "bin"),
            os.path.join("nvidia", "cublas", "bin"),
            os.path.join("nvidia", "cuda_runtime", "bin"),
            os.path.join("nvidia", "cuda_nvrtc", "bin"),
            os.path.join("nvidia", "cufft", "bin"),
            os.path.join("onnxruntime", "capi"),
        ]:
            p = os.path.abspath(os.path.join(b, rel))
            key = p.lower()
            if os.path.isdir(p) and key not in seen:
                seen.add(key)
                os.add_dll_directory(p)
                print("[PATH+]", p)


def check_win_dlls() -> None:
    deps = [
        "onnxruntime_providers_shared.dll",
        "cublas64_11.dll",
        "cublasLt64_11.dll",
        "cudnn64_8.dll",
        "cufft64_10.dll",
        "cudart64_110.dll",
        "MSVCP140.dll",
        "VCRUNTIME140.dll",
        "VCRUNTIME140_1.dll",
    ]
    for d in deps:
        try:
            ctypes.WinDLL(d)
            print("[OK ]", d)
        except Exception as e:
            print("[FAIL]", d, "->", e)


def check_onnx_session() -> None:
    models = glob.glob(os.path.expanduser("~/.insightface/models/buffalo_l/*.onnx"))
    if not models:
        print("[WARN] No insightface model found in ~/.insightface/models/buffalo_l")
        return

    for m in sorted(models):
        print("[MODEL]", m)
        sess = ort.InferenceSession(m, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        print("[ORT ] active providers:", sess.get_providers())


def check_insightface_wrapper() -> None:
    import insightface
    app = insightface.app.FaceAnalysis(
        name="buffalo_l",
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    app.prepare(ctx_id=0, det_size=(640, 640))
    print("[INS ] FaceAnalysis prepare OK")


if __name__ == "__main__":
    print("onnxruntime:", ort.__version__)
    print("available providers:", ort.get_available_providers())
    add_candidate_dirs()
    check_win_dlls()
    check_onnx_session()
    check_insightface_wrapper()
