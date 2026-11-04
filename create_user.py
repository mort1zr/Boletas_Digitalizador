"""Crea o reemplaza la cuenta local. Ejecutar en una terminal, no desde Streamlit."""
from getpass import getpass

import app_config
from auth_service import load_user, write_user


def main() -> None:
    print("Configuración de la cuenta local del Digitalizador de boletas")
    if load_user() is not None:
        answer = input("Ya existe una cuenta. ¿Deseas reemplazarla? [s/N]: ").strip().lower()
        if answer != "s":
            print("No se modificó la cuenta.")
            return
    username = input("Usuario (mínimo 3 caracteres): ").strip()
    password = getpass("Contraseña (mínimo 10 caracteres; no se mostrará): ")
    confirmation = getpass("Repite la contraseña: ")
    if password != confirmation:
        print("Las contraseñas no coinciden. No se guardó ningún cambio.")
        return
    try:
        write_user(username, password)
    except ValueError as exc:
        print(f"No se pudo crear la cuenta: {exc}")
        return
    print(f"Cuenta local creada en: {app_config.USERS_PATH}")
    print("El archivo guarda un hash con salt, no la contraseña en texto plano.")


if __name__ == "__main__":
    main()
