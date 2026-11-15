




class PaymentNotFoundError(Exception):
    pass


class PaymentAlreadyProcessedError(Exception):
    pass


class PaymentGatewayError(Exception):
    pass


class EmptyCartError(Exception):
    """Исключение: попытка оформить заказ с пустой корзиной"""
    pass


class WarehouseUnavailableError(Exception):
    pass


class WarehouseAuthError(Exception):
    pass


class ProductNotFoundError(Exception):
    pass


class InvalidFileTypeError(Exception):
    pass


class ProductNotFoundError(Exception):
    pass


class CartNotFoundError(Exception):
    pass
