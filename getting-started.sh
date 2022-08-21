#! /usr/bin/bash
clear
echo -e "\e[01;35m------ Getting Started Setup - (By Lucas Santos) ------\e[00m"
echo

# First update and upgrade
echo -e "\e[01;34mUpdate and Upgrade\e[00m"
sudo apt update &&
sudo apt upgrade -y &&
echo

# My Custom commands
echo -e "\e[01;34mCreate custom commands\e[00m"
echo

FILE=.bashrc
DEB_PATH=$HOME/Downloads/deb-files/

FILE_PATH=$HOME/$FILE

if [ -e $FILE_PATH ] ; then
echo -e "\e[01;32mArquivo $FILE encontrado com sucesso.\e[00m"
else
echo "\e[01;31mArquivo $FILE não encontrado.\e[00m"
echo "\e[00;34mCriando arquivo $FILE em $HOME...\e[00m"
touch $FILE_PATH
echo "\e[01;32mArquivo criado com sucesso.\e[00m"
fi

#Inserindo uma linha vazia
echo >> $FILE_PATH
#Inserindo alias no arquivo
echo "alias c='clear'" >> $FILE_PATH
echo "alias update='sudo apt update'" >> $FILE_PATH
echo "alias upgrade='sudo apt upgrade -y'" >> $FILE_PATH
echo "alias up='update && upgrade'" >> $FILE_PATH
echo "alias install='sudo apt install'" >> $FILE_PATH
echo "alias src='source $FILE_PATH'" >> $FILE_PATH


#Pacotes a serem intalados
echo -e "\e[01;34mInstalling some essential softwares\e[00m"
sudo apt-get install git wget ca-certificates curl gnupg lsb-release openssh-client open-ssh-server -y &&
sudo apt install openjdk-18-jdk -y &&
echo

#Instalando o docker engine
echo -e "\e[01;34mInstalling Docker Engine\e[00m"
sudo mkdir -p /etc/apt/keyrings &&
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg &&
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-compose -y
echo

if [ -e $DEB_PATH ] ; then
#Instalando packotes deb colocados na pasta informado em DEB_PATH
echo -e "\e[01;34mInstalling the packages that are in the DEB_PATH\e[00m"
FILES=$(ls $DEB_PATH)
for file in $FILES
do
sudo dpkg -i $DEB_PATH$file
done
echo
else
echo
fi

#Instalando o nvm
echo -e "\e[01;34mInstalling the nvm\e[00m"
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.1/install.sh | bash &&
echo

#configurar o android sdk para react native
echo -e "\e[01;34mConfig variable of the path to AndroidSDK for React Native\e[00m"
echo 'export ANDROID_SDK_ROOT=$HOME/android-sdk' >> $FILE_PATH
echo 'export PATH=$PATH:$ANDROID_SDK_ROOT/emulator' >> $FILE_PATH
echo 'export PATH=$PATH:$ANDROID_SDK_ROOT/platform-tools' >> $FILE_PATH
echo


echo "----- FINALIZADO COM SUCESSO -----"
