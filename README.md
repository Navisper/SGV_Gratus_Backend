# Gratus backend

Este es el **repositorio** para crear y manejar el desarrollo del backend para el sistema de gestion de ventas de la tienda **"Gratus"**. Esto como proyecto de clase en la universidad. El enfoque es crear un sistema que permita gestionar el inventario de la tienda, 
incluyendo funcionalidades como:

- CRUD para crear productos
- sistema de ventas 
- sistema de inventario
- manejo de descuentos y promociones
- login con google
- Base de datos en la nube
- etc

el proyecto esta en fases inciales, por lo que las funcionalidades estan sujetas a **cambios**

## Como configurar el repositorio

probablemente si estan leyendo esto es debido a que ya clonaron el repositorio en sus computadoras. Para poder ejecutar y editar de forma correcta sin dañar nada en el proceso, tienen que seguir los siguientes pasos.

### UV como package manager de python

El proyecto de python se gestiona mediante **uv**, una nueva herramienta que facilita la vida a los desarrolladores de python, la cual vi de total importancia ya que simplifica mucho el proceso de algunas cosas tediosas y que debido a ser un primer acercamiento 
para algunos en este ambiente, considero que es pertinente el uso para evitar confusiones

para instalar **UV** sigue estos pasos:

- Abre el cmd, powershell o herramienta para usar el terminal de tu preferencia.
- Copia y pega el siguiente comando en la terminal, ojo, asegurate de que sea el de tu sistema operativo
  - **Windows:** "winget install --id=astral-sh.uv -e"
  - **Mac(Con homembrew):** "brew install uv"
- Asegurate que se haya instalado de forma correcta escribiendo en el terminal "uv --version"

### Virtual enviroments y dependencias
Ahora que ya han instalado uv, lo siguiente va a ser muy facil.
Tenemos que usar la terminal teniendo en cuenta que este abierta en la direccion donde tienen el repositorio.
y escribir **"uv sync"**
- ejemplo c:/home/SGV_Gratus_Backend/backend-gratus> uv sync
de esta forma te aseguras de sincronizar las versiones y dependencias a las que se definen en el virtual enviroment

### Ejecutar codigo
Para poder ejecutar la app es necesario recordar que estamos usando el framework de fastAPI. El cual usa un paquete llamado uvicorn para la ejecucion del servidor.
En este caso para ejecutarlo vamos a usar el siguiente comando **"uv run uvicorn main:app"**. 
<br/>
Es recomendable que siempre que hagas un pull o vayas a ejecutar el proyecto, antes de usar el comando anterior, usar "uv sync" en caso de que exista algun nuevo paquete en uso del cual no te hayas enterado.

  
  
