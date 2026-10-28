# Assert Viewer para Java

Ferramenta experimental para Windows/Linux/macOS que abre uma GUI e transforma temporariamente asserts nativos em verificações individuais.

## Requisitos
- Python 3
- JDK instalado e `java` + `javac` disponíveis no PATH
- Tkinter (normalmente incluído no Python do Windows)

## Como usar
1. Extraia a pasta.
2. Execute `python assert_viewer.py`.
3. Selecione o arquivo de testes, por exemplo `LinkedListAsserts.java`.
4. Clique em **Executar e mostrar resultados**.

A ferramenta copia os `.java` da mesma pasta para um diretório temporário, instrumenta a cópia e compila/roda essa cópia. Não altera os arquivos originais.

## Limitações importantes
- A versão inicial instrumenta asserts que estão inteiros em uma única linha, como os do arquivo `LinkedListAsserts.java` enviado.
- Deve existir um `main()` que execute os métodos de teste.
- É um instrumentador simples, não um parser completo de Java. Código com `assert` em linhas múltiplas, packages complexos, dependências externas ou fontes geradas pode exigir ajustes.
- As verificações dentro de `try/catch` que foram feitas para esperar uma exceção continuam funcionando, mas a ferramenta pode mostrar como falha qualquer `assert false` alcançado quando a exceção esperada não ocorreu.
- A interface lista cada assert e a linha original, além do método atual.
