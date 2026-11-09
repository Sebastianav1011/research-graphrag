"""Shared console selector; sampling itself remains in project_selection.py."""


class SelectionCancelled(Exception):
    pass


def select_projects(seed=42, *, root=None, coordinator=None, config_path='config/pipeline_manual.json',allow_contracts=True):
    while True:
        print('\nProyectos a procesar\n1. Seleccionar cantidad de proyectos.\n2. Procesar todos los proyectos.')
        if allow_contracts:print('3. Contratos de evaluación')
        print('0. Cancelar.')
        try:
            option = input('Opcion: ').strip()
            if option == '0':
                raise SelectionCancelled()
            if option == '2':
                return dict(limit=None, all_projects=True, seed=seed)
            if option == '3' and allow_contracts:
                from pathlib import Path
                from evaluation_contracts import menu
                if coordinator is None:
                    from scripts import pipeline_coordinator as coordinator
                selection=menu(root or Path(__file__).resolve().parents[1],coordinator,config_path)
                if selection:return selection
                continue
            if option != '1':
                print('Opcion invalida.');continue
            while True:
                amount = input('¿Cuántos proyectos desea procesar?:').strip()
                if amount == '0':
                    raise SelectionCancelled()
                if amount.isascii() and amount.isdigit() and int(amount) > 0:
                    return dict(limit=int(amount), all_projects=False, seed=seed)
                print('Ingrese una cantidad entera positiva (0 para cancelar).')
        except EOFError:
            raise SelectionCancelled() from None
