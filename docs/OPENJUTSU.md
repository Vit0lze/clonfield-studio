# OpenJutsu H3

Fonte integrada: [Comfy-Org/comfy-openjutsu](https://github.com/Comfy-Org/comfy-openjutsu/tree/70ec62df0eda7c58697ea3ac2050588513651583). O código, o grafo original, a licença MIT e os avisos de terceiros ficam em `vendor/openjutsu/`. O patch do node pack mantém a licença GPL-3.0.

No ClonField, o formulário usa o grafo local com clipe e imagem do personagem, início, duração, resolução, seed e primeiro quadro opcional fornecido por você. A coleta usa o mesmo histórico dos outros grafos. A rota local não chama o serviço de criação de quadro do upstream.

O upstream executou esse perfil em RTX PRO 6000 de 96 GB. A T4 é bloqueada antes de preparar os pesos deste perfil. Para um worker compatível, leia os [requisitos e termos dos pesos](../vendor/openjutsu/build/model-files.md), aceite o acesso aos modelos aplicáveis no Hugging Face e ligue `PREPARE_OPENJUTSU` na célula do worker antes de iniciar o ComfyUI. A instalação usa o pack Akatz fixado, o patch upstream e as revisões de pesos documentadas. Se o worker já estiver ativo, pare-o antes de preparar o OpenJutsu.

O código Next.js original está disponível separadamente para quem já tem deployment e credenciais da Comfy Developer Platform. Seu uso pode consumir créditos da conta. O caminho local do ClonField usa ComfyUI em loopback.
