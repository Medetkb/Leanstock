# Import models here so SQLModel metadata registers all tables
from app.models.user import Tenant, User, RefreshToken, EmailVerification, PasswordResetToken  # noqa
from app.models.product import Product  # noqa
from app.models.inventory import Location, Inventory, InventoryTransfer, AuditLog  # noqa
from app.models.supplier import Supplier, PurchaseOrder, PurchaseOrderItem  # noqa
from app.models.reservation import Reservation  # noqa
