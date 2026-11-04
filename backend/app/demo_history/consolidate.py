"""Unificación puntual de la demo; sin respaldos ni cambios al esquema.

python -m app.demo_history.consolidate [--execute]
Sin --execute verifica toda la operación y revierte la transacción.
"""
import argparse
from pathlib import Path
from collections import Counter

from dotenv import dotenv_values, set_key
from sqlalchemy import MetaData, select, text, update, delete, insert
from sqlalchemy.orm import Session

from app.db.engine import build_engine
from app.auth.security import hash_password, verify_password
from app.menu.service import refresh_recipe_costs


def consolidate(connection, password):
    connection.execute(text("SET LOCAL lock_timeout = '10s'"))
    connection.execute(text('SELECT pg_advisory_xact_lock(1647042, 1)'))
    metadata = MetaData()
    metadata.reflect(connection, schema='public')
    tables = {t.name: t for t in metadata.tables.values()}
    expected = {'restaurante', 'usuario', 'cliente', 'repartidor', 'producto', 'insumo',
        'pedido', 'detalle_pedido', 'receta_detalle', 'entrega', 'historial_pedido',
        'movimiento_stock', 'historial_repartidor', 'alerta', 'prediccion_demanda',
        'auth_sesion', 'auth_estado_acceso', 'alembic_version'}
    if set(tables) != expected:
        raise ValueError('El esquema contiene tablas no contempladas; revisar relaciones antes de continuar.')
    connection.execute(text('LOCK TABLE ' + ','.join('public.' + n for n in sorted(expected)) + ' IN ACCESS EXCLUSIVE MODE'))
    def rows(name):
        return [dict(r) for r in connection.execute(select(tables[name])).mappings()]
    restaurants = rows('restaurante')
    if any(r['nombre'] != 'Rotisería del Pueblo' for r in restaurants):
        raise ValueError('Hay restaurantes ajenos al conjunto de demostración.')
    users = rows('usuario')
    by_id = {u['id_usuario']: u for u in users}
    # Identidades existentes verificadas en la inspección, no reglas de negocio.
    chosen = {'propietario': 1, 'personal': 2, 'cliente': 4,
              'repartidor': 3, 'repartidor_2': 60, 'repartidor_3': 61}
    for role, uid in chosen.items():
        if uid not in by_id or by_id[uid]['rol'] != role.split('_')[0]:
            raise ValueError('Las cuentas seleccionadas no coinciden con la inspección.')
    keep = set(chosen.values())
    customers = rows('cliente')
    client_id = next(c['id_cliente'] for c in customers if c['id_usuario'] == chosen['cliente'])
    couriers = rows('repartidor')
    final_couriers = [next(c['id_repartidor'] for c in couriers if c['id_usuario'] == chosen[key])
                      for key in ('repartidor', 'repartidor_2', 'repartidor_3')]
    mapping = {c['id_repartidor']: (c['id_repartidor'] if c['id_repartidor'] in final_couriers
        else final_couriers[i % 3]) for i, c in enumerate(sorted(couriers, key=lambda r:r['id_repartidor']))}
    preserved = {name: rows(name) for name in ('detalle_pedido', 'receta_detalle', 'entrega', 'historial_pedido', 'movimiento_stock')}
    before_orders = rows('pedido')
    active = Counter(mapping[e['id_repartidor']] for e in preserved['entrega'] if e['estado'] in ('Asignado', 'En camino', 'asignada'))
    if any(n > 1 for n in active.values()):
        raise ValueError('La reasignación produciría entregas activas incompatibles; no se fuerza.')
    # Retirar y reconstruir relaciones dentro de la misma transacción conserva PK,
    # fechas, importes y contenido. Los triggers y FK permanecen activos.
    for name in preserved:
        connection.execute(delete(tables[name]))
    if not any(r['id_restaurante'] == 1 for r in restaurants):
        source = min(restaurants, key=lambda r:r['id_restaurante']).copy()
        source['id_restaurante'] = 1
        connection.execute(insert(tables['restaurante']), source)
    for name in ('usuario', 'producto', 'insumo', 'pedido', 'alerta'):
        connection.execute(update(tables[name]).values(id_restaurante=1))
    connection.execute(update(tables['pedido']).values(id_cliente=client_id))
    for old, new in mapping.items():
        connection.execute(update(tables['historial_repartidor']).where(tables['historial_repartidor'].c.id_repartidor == old).values(id_repartidor=new))
    for row in preserved['entrega']:
        row['id_repartidor'] = mapping[row['id_repartidor']]
    actor_map = {}
    for old in users:
        uid = old['id_usuario']
        if uid in keep:
            actor_map[uid] = uid
        elif old['rol'] == 'repartidor':
            old_courier = next(c for c in couriers if c['id_usuario'] == uid)
            actor_map[uid] = next(c['id_usuario'] for c in couriers if c['id_repartidor'] == mapping[old_courier['id_repartidor']])
        else:
            actor_map[uid] = chosen.get(old['rol'], chosen['propietario'])
    for row in preserved['historial_pedido']:
        old = row['id_usuario']
        row['id_usuario'] = actor_map[old]
        if old != row['id_usuario']:
            row['detalle'] = (row['detalle'] or '') + f' [Demo: actor original #{old}, {by_id[old]["nombre"]}]'
    for name, data in preserved.items():
        for start in range(0, len(data), 500):
            connection.execute(insert(tables[name]), data[start:start + 500])
    connection.execute(delete(tables['auth_sesion']))
    connection.execute(delete(tables['auth_estado_acceso']))
    connection.execute(delete(tables['cliente']).where(tables['cliente'].c.id_cliente != client_id))
    connection.execute(delete(tables['repartidor']).where(tables['repartidor'].c.id_repartidor.not_in(final_couriers)))
    connection.execute(delete(tables['usuario']).where(tables['usuario'].c.id_usuario.not_in(keep)))
    connection.execute(delete(tables['restaurante']).where(tables['restaurante'].c.id_restaurante != 1))
    for uid in keep:
        encoded = hash_password(password)
        assert verify_password(encoded, password)
        connection.execute(update(tables['usuario']).where(tables['usuario'].c.id_usuario == uid).values(hash_contrasena=encoded, activo=True))
    with Session(connection, join_transaction_mode='create_savepoint') as db:
        refresh_recipe_costs(db, 1)
        db.commit()
    connection.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
    after_orders = rows('pedido')
    without_scope = lambda data: sorted((r['id_pedido'], r['fecha_hora'], r['importe_total'], r['costo_total'], r['estado'], r['estado_pago']) for r in data)
    if without_scope(before_orders) != without_scope(after_orders):
        raise ValueError('Cambió el historial de pedidos; se revierte.')
    for name, data in preserved.items():
        if sorted(rows(name), key=str) != sorted(data, key=str):
            raise ValueError('No coincide la reconstrucción de ' + name)
    assert len(rows('usuario')) == 6 and len(rows('restaurante')) == 1
    return {role: by_id[uid]['correo'] for role, uid in chosen.items()}, len(after_orders)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    env = Path(__file__).resolve().parents[3] / 'frontend' / '.env.development.local'
    password = dotenv_values(env).get('LOCAL_ACCOUNT_PASSWORD')
    if not password:
        raise ValueError('Falta la contraseña local privada; no se imprimen credenciales.')
    with build_engine().connect() as connection:
        with connection.begin() as transaction:
            accounts, count = consolidate(connection, password)
            if not args.execute:
                transaction.rollback()
    if args.execute:
        for role, email in accounts.items():
            set_key(env, f'LOCAL_ACCOUNT_{role.upper()}_EMAIL', email)
    print(('Aplicado' if args.execute else 'Verificado con rollback') + f': 1 restaurante, 6 usuarios, {count} pedidos conservados.')


if __name__ == '__main__':
    main()
