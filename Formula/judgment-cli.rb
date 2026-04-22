class JudgmentCli < Formula
  include Language::Python::Virtualenv

  desc "CLI for the Judgment API"
  homepage "https://github.com/JudgmentLabs/cli"
  # Update url + sha256 when cutting a release. See README.md
  # ("Releasing a new Homebrew version") for the full procedure.
  url "https://github.com/JudgmentLabs/cli/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "PLACEHOLDER_SHA256"
  license "MIT"

  depends_on "python@3.12"

  resource "click" do
    url "https://files.pythonhosted.org/packages/96/d3/f04c7bfcf5c1862a2a5b845c6b2b360488cf47af55dfa79c98f6a6bf98b5/click-8.1.7.tar.gz"
    sha256 "ca9853ad459e787e2192211578cc907e7594e294c7ccc834310722b41b9ca6de"
  end

  resource "httpx" do
    url "https://files.pythonhosted.org/packages/78/82/08f8c936781f67d9e6b9eeb925a9f092394c472a8e1050e59cd0a5e1e4e6/httpx-0.28.1.tar.gz"
    sha256 "75e98c5f16b0f35b567856f928611571a781e6f405c16d9c22f98e45c2b406ab"
  end

  resource "httpcore" do
    url "https://files.pythonhosted.org/packages/06/94/82699a10bca87a5556c9c59b5963f2d039dbd239f25bc2a63907a05a14cb/httpcore-1.0.7.tar.gz"
    sha256 "8551cb62a169ec7162ac7be8d4817d561f60e08eaa485234898414bb5a8a0b12"
  end

  resource "certifi" do
    url "https://files.pythonhosted.org/packages/37/31/7f846e8a7e97e5dbce7aee3d5dc91a0b5788f7d5a33edfee75e0c246fade/certifi-2025.1.31.tar.gz"
    sha256 "3d5da6925056f6f18f119200434a4780a94263f10d1c21d032a6f6b2baa20651"
  end

  resource "idna" do
    url "https://files.pythonhosted.org/packages/f1/70/7703c29685631f5a7590aa73f1f1d3fa9a380e654b86af429e0934a32f7d/idna-3.10.tar.gz"
    sha256 "12f65c9b470abda6dc35cf8e63cc574b1c52b11df2c86030af0ac09b01b13ea9"
  end

  resource "sniffio" do
    url "https://files.pythonhosted.org/packages/a2/87/a6771e1546d97e7e041b6ae58d80074f81b7d5121207425c964ddf5cfdbd/sniffio-1.3.1.tar.gz"
    sha256 "f4324edc670a0f49750a81b895f35c3adb843cca46f0530f79fc1babb23789dc"
  end

  resource "anyio" do
    url "https://files.pythonhosted.org/packages/95/7d/4c1bd541d4dffa1b52bd83fb8527089e097a106fc90b467a7313b105f840/anyio-4.8.0.tar.gz"
    sha256 "1d9fe889df5212571f3e4ae3b2f47e4ca2b2d55c0e4f14263a83e0c4d8741f55"
  end

  resource "h11" do
    url "https://files.pythonhosted.org/packages/f5/38/3af3d3633a34a3316095b39c8e8fb4853a28a536e55d347bd8d8e9a14b03/h11-0.14.0.tar.gz"
    sha256 "8f09a5220f5a5e34e3e27d7e89d4a7e87f4e4b806c8e60e3ab2bfb4bc65d3e0e"
  end

  resource "platformdirs" do
    url "https://files.pythonhosted.org/packages/9f/4a/0883b8e3802965322523f0b200ecf33d31f10991d0401162f4b23c698b42/platformdirs-4.9.6.tar.gz"
    sha256 "3bfa75b0ad0db84096ae777218481852c0ebc6c727b3168c1b9e0118e458cf0a"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "judgment", shell_output("#{bin}/judgment --version")
  end
end
