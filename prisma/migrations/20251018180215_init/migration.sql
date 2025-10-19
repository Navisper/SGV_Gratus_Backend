-- CreateEnum
CREATE TYPE "AuthProvider" AS ENUM ('GOOGLE', 'EMAIL', 'GITHUB', 'LOCAL');

-- CreateTable
CREATE TABLE "users" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "nombre" VARCHAR(100),
    "email" VARCHAR(150) NOT NULL,
    "password_hash" TEXT,
    "rol" VARCHAR(20) NOT NULL DEFAULT 'admin',
    "provider" "AuthProvider" NOT NULL DEFAULT 'EMAIL',
    "google_sub" TEXT,
    "avatar_url" VARCHAR(300),
    "tienda_id" UUID,
    "created_at" TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(6) NOT NULL,

    CONSTRAINT "users_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "stores" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "nombre" VARCHAR(100),
    "direccion" TEXT,
    "created_at" TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "stores_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "products" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "codigo_unico" VARCHAR(50),
    "nombre" VARCHAR(150),
    "categoria" VARCHAR(100),
    "departamento" VARCHAR(100),
    "tipo" VARCHAR(100),
    "costo" DECIMAL(10,2),
    "precio" DECIMAL(10,2),
    "stock" INTEGER DEFAULT 0,
    "tienda_id" UUID,
    "created_at" TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "products_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "sales" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "usuario_id" UUID,
    "tienda_id" UUID,
    "total" DECIMAL(10,2),
    "descuento" DECIMAL(10,2) DEFAULT 0,
    "metodo_pago" VARCHAR(50),
    "created_at" TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "sales_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "sale_items" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "venta_id" UUID,
    "producto_id" UUID,
    "cantidad" INTEGER,
    "precio_unitario" DECIMAL(10,2),
    "subtotal" DECIMAL(10,2),

    CONSTRAINT "sale_items_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "invoices" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "venta_id" UUID,
    "consecutivo" SERIAL NOT NULL,
    "pdf_url" TEXT,
    "impresa" BOOLEAN DEFAULT false,
    "created_at" TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "invoices_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "users_email_key" ON "users"("email");

-- CreateIndex
CREATE UNIQUE INDEX "users_google_sub_key" ON "users"("google_sub");

-- CreateIndex
CREATE UNIQUE INDEX "products_codigo_unico_key" ON "products"("codigo_unico");

-- AddForeignKey
ALTER TABLE "products" ADD CONSTRAINT "products_tienda_id_fkey" FOREIGN KEY ("tienda_id") REFERENCES "stores"("id") ON DELETE NO ACTION ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "sales" ADD CONSTRAINT "sales_tienda_id_fkey" FOREIGN KEY ("tienda_id") REFERENCES "stores"("id") ON DELETE NO ACTION ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "sales" ADD CONSTRAINT "sales_usuario_id_fkey" FOREIGN KEY ("usuario_id") REFERENCES "users"("id") ON DELETE NO ACTION ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "sale_items" ADD CONSTRAINT "sale_items_producto_id_fkey" FOREIGN KEY ("producto_id") REFERENCES "products"("id") ON DELETE NO ACTION ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "sale_items" ADD CONSTRAINT "sale_items_venta_id_fkey" FOREIGN KEY ("venta_id") REFERENCES "sales"("id") ON DELETE NO ACTION ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "invoices" ADD CONSTRAINT "invoices_venta_id_fkey" FOREIGN KEY ("venta_id") REFERENCES "sales"("id") ON DELETE NO ACTION ON UPDATE NO ACTION;
