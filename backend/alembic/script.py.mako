"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

# Alembic 使用本模板生成新的迁移文件；修订标识和迁移语句由生成器填充。
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    # 按正向依赖顺序应用本次结构变更。
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    # 以可逆的相反顺序撤销本次结构变更。
    ${downgrades if downgrades else "pass"}
